import argparse, concurrent.futures, os, shlex, shutil, subprocess
from pathlib import Path

from xklb import usage
from xklb.mediafiles import process_image
from xklb.utils import arggroups, argparse_utils, consts, devices, file_utils, path_utils, processes, web
from xklb.utils.arg_utils import gen_paths
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_text)
    parser.add_argument("--delete-unplayable", action="store_true")
    parser.add_argument("--max-image-height", type=int, default=2400)
    parser.add_argument("--max-image-width", type=int, default=2400)
    parser.add_argument(
        "--delete-larger",
        "--delete-original",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Delete larger of transcode or original files",
    )
    parser.add_argument("--clean-path", action=argparse.BooleanOptionalAction, default=True, help="Clean output path")
    arggroups.clobber(parser)
    arggroups.ocrmypdf(parser)
    arggroups.requests(parser)
    arggroups.download(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.ocrmypdf_post(args)
    return args


def get_calibre_version():
    result = processes.cmd("ebook-convert", "--version")

    version_string = result.stdout
    version_part = version_string.split("(")[1].split(")")[0].split()[1]

    major, minor, patch = map(int, version_part.split("."))

    return (major, minor, patch)


def update_references(path, replacements):
    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read()

        for old, new in replacements.items():
            content = content.replace(old, new)

        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

    except Exception:
        log.exception("Error occurred while updating references %s", path)


def convert_to_text_pdf(args, path):
    import ocrmypdf, ocrmypdf.exceptions

    ext = path_utils.ext(path)

    pdf_path = path
    if ext != "pdf":
        pdf_path = str(Path(pdf_path).with_suffix(".pdf"))
        pdf_path = devices.clobber_new_file(args, pdf_path)

    try:
        kwargs = {}

        kwargs["optimize"] = 0
        kwargs["output_type"] = "pdf"
        kwargs["fast_web_view"] = 999999

        TESSERACT_LANGUAGE = os.getenv("TESSERACT_LANGUAGE")
        if TESSERACT_LANGUAGE:
            kwargs["language"] = TESSERACT_LANGUAGE.split(",")

        kwargs["skip_text"] = args.skip_text
        kwargs["redo_ocr"] = args.redo_ocr
        kwargs["force_ocr"] = args.force_ocr

        result = ocrmypdf.ocr(path, pdf_path, **kwargs)
        log.debug(result)
    except ocrmypdf.exceptions.EncryptedPdfError:
        log.info("[%s]: Skipped PDF OCR because it is encrypted", path)
    except ocrmypdf.exceptions.DigitalSignatureError:
        log.info("[%s]: Skipped PDF because it has a digital signature", path)
    except (ocrmypdf.exceptions.TaggedPDFError, ocrmypdf.exceptions.PriorOcrFoundError):
        log.info("[%s]: Skipped PDF because it already contained text", path)
    except Exception as e:
        log.warning("[%s]: Could not run OCR. %s", path, e)
    else:
        if os.path.exists(pdf_path):
            if args.delete_larger and not os.path.samefile(path, pdf_path):
                os.unlink(path)
            path = pdf_path

    return path


def process_path(args, path):
    if str(path).startswith("http"):
        if args.simulate:
            log.info("Downloading %s", path)
        else:
            path = web.download_url(args, path)
        if path is None:
            log.error("Could not save URL %s", path)
            return None

    path = Path(path).resolve()

    ext = path_utils.ext(path)

    if ext in consts.OCRMYPDF_EXTENSIONS and not args.no_ocr:
        import ocrmypdf

        if args.simulate:
            log.info("Running OCR on %s", path)
        else:
            if not ocrmypdf.pdfa.file_claims_pdfa(Path(path))["pass"]:
                path = convert_to_text_pdf(args, path)

    ext = path_utils.ext(path)

    if ext not in consts.CALIBRE_EXTENSIONS:
        return path

    p = Path(path)
    output_path = p.parent
    output_path /= p.stem + ".OEB"
    if args.clean_path:
        output_path = path_utils.clean_path(os.fsencode(output_path))

    if os.path.isdir(output_path):
        # we need to make sure the target folder is empty because we possibly call rmtree later
        existing_rename = file_utils.alt_name(output_path)
        devices.rename(args, output_path, existing_rename)
    else:
        path, output_path = devices.clobber(args, path, output_path)
        if path is None:
            return output_path

    path = Path(path)
    output_path = Path(output_path)

    output_path.parent.mkdir(exist_ok=True, parents=True)
    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)

    # TODO: add .doc support with antiword or libre-office https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html

    command = [
        "ebook-convert",
        str(path),
        str(output_path),
        "--minimum-line-height=105",
        "--unsmarten-punctuation",
        # "--insert-blank-line",
        # "--add-alt-text-to-img",
        # '--disable-font-rescaling',
        # '--enable-heuristics',
        # '--input-encoding',
        # '--change-justification left',
        # '--subset-embedded-fonts',
        # '--linearize-tables',
    ]

    if get_calibre_version() >= (7, 19, 0):
        command += ["--pdf-engine", "pdftohtml"]

    if args.simulate:
        print(shlex.join(command))
        return path

    try:
        original_stats = path.stat()
    except FileNotFoundError:
        log.error("File not found: %s", path)
        return None

    try:
        processes.cmd(*command)
    except subprocess.CalledProcessError:
        log.exception("[%s]: Calibre failed to process book. Skipping...", str(path))
        return path

    if not output_path.exists() or path_utils.is_empty_folder(output_path):
        output_path.unlink()  # Remove transcode
        log.error("Could not transcode %s", path)
        return path

    # replace CSS
    base_folder = Path(__file__).resolve().parent
    shutil.copy(base_folder / ".." / "assets" / "calibre.css", output_path / "stylesheet.css")

    # shrink images
    image_paths = file_utils.rglob(str(output_path), consts.IMAGE_EXTENSIONS, quiet=True)[0]

    mp_image_args = argparse.Namespace(
        **{k: v for k, v in args.__dict__.items() if k not in {"db"}} | {"delete_larger": True}
    )
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            image_path: executor.submit(process_image.process_path, mp_image_args, image_path)
            for image_path in image_paths
        }
    avif_files = {k: v.result() for k, v in futures.items()}

    replacements = {"image/jpeg": "image/avif"} | {
        os.path.basename(old): os.path.basename(new) for old, new in avif_files.items() if new
    }
    text_paths = file_utils.rglob(str(output_path), consts.PLAIN_EXTENSIONS, quiet=True)[0]
    for text_path in text_paths:
        update_references(text_path, replacements)

    # compare final output size
    if args.delete_larger and path_utils.folder_size(output_path) > original_stats.st_size:
        devices.rmtree(args, output_path)  # Remove transcode
        return path

    if args.delete_larger:
        path.unlink()  # Remove original
    path_utils.folder_utime(output_path, (original_stats.st_atime, original_stats.st_mtime))

    return output_path


def process_text():
    args = parse_args()

    if not shutil.which("ebook-convert"):
        print("Calibre is required for process-text")
        raise SystemExit(1)

    for path in gen_paths(args, consts.CALIBRE_EXTENSIONS | consts.OCRMYPDF_EXTENSIONS):
        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_text()
