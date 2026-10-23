import argparse, concurrent.futures, os, shlex, shutil, subprocess
from pathlib import Path

from library import usage
from library.shrink import process_image
from library.utils import arggroups, argparse_utils, consts, devices, path_utils, processes, shell_utils, web
from library.utils.log_utils import log
from library.utils.shell_utils import gen_paths

_EPUB_SIMULATION = object()


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_text)
    parser.add_argument("--delete-unplayable", action="store_true")
    parser.add_argument("--max-image-height", type=int, default=2400)
    parser.add_argument("--max-image-width", type=int, default=2400)
    parser.add_argument(
        "--delete-larger",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Delete larger of transcode or original files",
    )
    parser.add_argument(
        "--delete-original",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Delete the original after a successful transcode",
    )
    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-dest")
    arggroups.ocrmypdf(parser)
    arggroups.requests(parser)
    arggroups.download(parser, profile=False)
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
        content = Path(path).read_text(encoding="utf-8")

        for old, new in replacements.items():
            content = content.replace(old, new)

        Path(path).write_text(content, encoding="utf-8")

    except Exception:
        log.exception("Error occurred while updating references %s", path)


def get_media_type(ext):
    """Return MIME type for a file extension."""
    ext = ext.lower()
    media_types = {
        ".avif": "image/avif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    return media_types.get(ext)


def update_manifest(output_path, avif_files):
    """Update content.opf manifest with converted image references."""
    manifest_path = output_path / "content.opf"

    try:
        content = Path(manifest_path).read_text(encoding="utf-8")
    except Exception as e:
        log.warning("Failed to read content.opf: %s", e)
        return

    modified = False

    # Build mapping of old basename -> new basename for converted files
    for old_path, new_path in avif_files.items():
        if not new_path:
            continue

        old_name = os.path.basename(old_path)
        new_name = os.path.basename(new_path)
        new_ext = os.path.splitext(new_name)[1]
        new_media_type = get_media_type(new_ext)

        # Replace href attributes in manifest items
        # Pattern: href="images/old.jpg" -> href="images/old.avif"
        if f'href="{old_name}"' in content:
            content = content.replace(f'href="{old_name}"', f'href="{new_name}"')
            modified = True
        if f"href='{old_name}'" in content:
            content = content.replace(f"href='{old_name}'", f"href='{new_name}'")
            modified = True

        # Update media-type attribute for this item
        if new_media_type:
            # Find the item line containing this file and update its media-type
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if "<item" in line and old_name in line:
                    # Update media-type attribute
                    old_media_type = get_media_type(os.path.splitext(old_name)[1])
                    if old_media_type and f'media-type="{old_media_type}"' in line:
                        lines[i] = line.replace(f'media-type="{old_media_type}"', f'media-type="{new_media_type}"')
                        modified = True
            content = "\n".join(lines)

    if modified:
        try:
            Path(manifest_path).write_text(content, encoding="utf-8")
        except Exception as e:
            log.warning("Failed to write content.opf: %s", e)


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
    except Exception as excinfo:
        log.warning("[%s]: Could not run OCR. %s", path, excinfo)
    else:
        if os.path.exists(pdf_path):
            if (args.delete_larger or args.delete_original) and not os.path.samefile(path, pdf_path):
                os.unlink(path)
            path = pdf_path

    return path


def _prepare_text_path(args, path):
    if str(path).startswith("http"):
        if args.simulate:
            log.info("Downloading %s", path)
        else:
            path = web.download_url(args, path)
        if path is None:
            log.error("Could not save URL %s", path)
            return None
    return Path(path).resolve()


def _process_text_ocr(args, path):
    ext = path_utils.ext(path)
    if ext in consts.OCRMYPDF_EXTENSIONS and not args.no_ocr:
        import ocrmypdf

        if args.simulate:
            log.info("Running OCR on %s", path)
        else:
            import pikepdf

            try:
                if (
                    args.redo_ocr
                    or args.skip_text
                    or args.force_ocr
                    or not ocrmypdf.pdfa.file_claims_pdfa(Path(path))["pass"]
                ):
                    path = convert_to_text_pdf(args, path)
            except pikepdf.PdfError:
                log.exception("[%s]: could not open as PDF", path)
    return path


def _calibre_command(path, output_path, ext):
    command = [
        "ebook-convert",
        str(path),
        str(output_path),
        "--minimum-line-height=105",
        "--unsmarten-punctuation",
    ]
    if ext == "pdf" and get_calibre_version() >= (7, 19, 0):
        command += ["--pdf-engine", "pdftohtml"]
    return command


def _shrink_book_images(args, output_path):
    image_paths = shell_utils.rglob(str(output_path), consts.IMAGE_EXTENSIONS, quiet=True)[0]
    mp_image_args = argparse.Namespace(
        **{k: v for k, v in args.__dict__.items() if k != "db"} | {"delete_larger": True, "delete_original": False}
    )
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            image_path: executor.submit(process_image.process_path, mp_image_args, image_path)
            for image_path in image_paths
        }
    return {k: v.result() for k, v in futures.items()}


def _package_epub(args, opf_path, epub_path, css_path):
    epub_command = [
        "ebook-convert",
        str(opf_path),
        str(epub_path),
        "--no-default-epub-cover",
        "--epub-inline-toc",
        "--dont-split-on-page-breaks",
        "--epub-max-image-size=none",
        "--output-profile tablet",
        f"--extra-css={css_path}",
    ]
    if args.simulate:
        print(shlex.join(epub_command))
        return _EPUB_SIMULATION
    try:
        processes.cmd(*epub_command, limit_ram=True, nice=6)
    except subprocess.CalledProcessError:
        log.exception("[%s]: Calibre failed to package EPUB", opf_path.parent)
        epub_path.unlink(missing_ok=True)
        return str(opf_path)
    if not epub_path.exists():
        log.error("Could not create EPUB %s", opf_path)
        return str(opf_path)
    return None


def _prepare_calibre_output(args, path, output_path):
    if os.path.isdir(output_path):
        existing_rename = devices.alt_name(output_path)
        devices.rename(args, output_path, existing_rename)
        return path, output_path
    return devices.clobber(args, path, output_path)


def _run_calibre_conversion(args, path, output_path, ext):
    path = Path(path)
    output_path = Path(output_path)
    if not args.simulate:
        output_path.parent.mkdir(exist_ok=True, parents=True)
    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)

    try:
        original_stats = path.stat()
    except FileNotFoundError:
        log.error("File not found: %s", path)
        return None, None, None

    try:
        processes.cmd(*_calibre_command(path, output_path, ext), limit_ram=True, nice=6)
    except subprocess.CalledProcessError:
        log.exception("[%s]: Calibre failed to process book. Skipping...", str(path))
        if output_path.exists():
            devices.rmtree(args, output_path)
        return str(path), None, original_stats

    if not output_path.exists() or path_utils.is_empty_folder(output_path):
        log.error("Could not transcode %s", path)
        if output_path.exists():
            output_path.rmdir()
        return str(path), None, original_stats
    return str(path), output_path, original_stats


def _repackage_calibre_book(args, path, output_path, original_stats):
    avif_files = _shrink_book_images(args, output_path)
    replacements = {"image/jpeg": "image/avif"} | {
        os.path.basename(old): os.path.basename(new) for old, new in avif_files.items() if new
    }
    text_paths = shell_utils.rglob(str(output_path), consts.PLAIN_EXTENSIONS, quiet=True)[0]
    for text_path in text_paths:
        update_references(text_path, replacements)
    if any(avif_files.values()):
        update_manifest(output_path, avif_files)

    opf_path = output_path / "content.opf"
    epub_path = output_path.with_suffix(".OEB.epub")
    epub_path = Path(devices.clobber_new_file(args, str(epub_path)))
    base_folder = Path(__file__).resolve().parent
    css_path = str((base_folder / ".." / "assets" / "calibre.css").resolve())
    package_result = _package_epub(args, opf_path, epub_path, css_path)
    if package_result is not None:
        return str(path)

    devices.rmtree(args, output_path)
    epub_size = os.path.getsize(epub_path)
    if args.delete_larger and not args.delete_original and epub_size > original_stats.st_size:
        epub_path.unlink(missing_ok=True)
        return str(path)
    if args.delete_larger or args.delete_original:
        Path(path).unlink()
    return str(epub_path)


def process_path(args, path) -> str | None:
    path = _prepare_text_path(args, path)
    if path is None:
        return None
    path = _process_text_ocr(args, path)

    ext = path_utils.ext(path)

    if ext not in consts.CALIBRE_EXTENSIONS:
        return str(path)

    p = Path(path)
    output_path = p.parent
    output_path /= p.stem + ".OEB"
    if args.clean_path:
        output_path = path_utils.clean_path(os.fsencode(output_path))

    if args.simulate:
        command = _calibre_command(path, output_path, ext)
        print(shlex.join(command))
        return str(path)

    path, output_path = _prepare_calibre_output(args, path, output_path)
    if path is None:
        return output_path
    converted_path, converted_output, original_stats = _run_calibre_conversion(args, path, output_path, ext)
    if original_stats is None or converted_output is None:
        return converted_path
    return _repackage_calibre_book(args, converted_path, converted_output, original_stats)


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
