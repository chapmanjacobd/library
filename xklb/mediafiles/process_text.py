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
        "--delete-original", action=argparse.BooleanOptionalAction, default=True, help="Delete source files"
    )
    parser.add_argument("--clean-path", action=argparse.BooleanOptionalAction, default=True, help="Clean output path")
    arggroups.clobber(parser)
    arggroups.requests(parser)
    arggroups.download(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


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


def process_path(args, path):
    if str(path).startswith("http"):
        path = web.download_url(args, path)
        if path is None:
            log.error("Could not save URL %s", path)
            return None

    ext = os.path.splitext(path)[1].lower().lstrip(".")
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

    try:
        original_stats = path.stat()
    except FileNotFoundError:
        log.error("File not found: %s", path)
        return None

    # TODO: add .doc support with libre-office https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html

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

    if args.simulate:
        print(shlex.join(command))
        return path

    try:
        processes.cmd(*command)
    except subprocess.CalledProcessError:
        raise

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
        **{k: v for k, v in args.__dict__.items() if k not in {"db"}} | {"delete_original": True}
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
    if path_utils.folder_size(output_path) > original_stats.st_size:
        devices.rmtree(args, output_path)  # Remove transcode
        return path

    if args.delete_original:
        path.unlink()  # Remove original
    path_utils.folder_utime(output_path, (original_stats.st_atime, original_stats.st_mtime))

    return output_path


def process_text():
    args = parse_args()

    for path in gen_paths(args, consts.CALIBRE_EXTENSIONS):
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_text()
