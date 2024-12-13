import argparse, os, subprocess
from pathlib import Path

from natsort import natsorted

from library import usage
from library.utils import arggroups, argparse_utils, consts, devices, file_utils, path_utils, processes, web
from library.utils.date_utils import utc_from_local_timestamp
from library.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.images_to_pdf)
    parser.add_argument(
        "--delete-original", action=argparse.BooleanOptionalAction, default=False, help="Delete source images"
    )

    parser.add_argument("--output-path", "-o", help="Output PDF file (optional)")
    arggroups.clobber(parser)
    arggroups.requests(parser)
    arggroups.download(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


DEFAULT_EXTENSIONS = (consts.IMAGE_EXTENSIONS | consts.PIL_EXTENSIONS) - {"pdf"}  # type: ignore


def gen_pillow_compats(input_paths):
    for input_path in input_paths:
        if path_utils.ext(input_path) in consts.PIL_EXTENSIONS:
            if os.path.getsize(input_path) == 0:
                log.warning("[%s]: skipping empty file", input_path)
            else:
                yield input_path
        else:  # consts.IMAGE_EXTENSIONS - consts.PIL_EXTENSIONS
            data = subprocess.run(["magick", input_path, "jpg:-"], stdout=subprocess.PIPE, check=True).stdout
            if data:
                yield data


def convert_to_image_pdf(args, image_paths, pdf_path):
    import img2pdf

    image_stats = os.stat(image_paths[0])
    creation_date = utc_from_local_timestamp(image_stats.st_ctime)
    modified_date = utc_from_local_timestamp(image_stats.st_mtime)

    pdf_path = devices.clobber_new_file(args, pdf_path)

    log.debug("Converting %s images to PDF %s", len(image_paths), pdf_path)

    with open(pdf_path, "wb") as f:
        img2pdf.convert(
            *list(gen_pillow_compats(image_paths)),
            outputstream=f,
            rotation=img2pdf.Rotation.ifvalid,
            creationdate=creation_date,
            moddate=modified_date,
        )

    if args.delete_original and os.path.exists(pdf_path):
        for image_path in image_paths:
            os.unlink(image_path)

    return pdf_path


def process_paths(args, paths):
    paths = natsorted(paths)

    pdf_path = args.output_path
    if pdf_path is None:
        prefix = os.path.commonprefix(paths)
        parent = str(Path(paths[0]).parent)

        basename = parent
        if len(prefix) > len(basename):
            basename = prefix

        pdf_path = str(Path(basename).with_suffix(".pdf"))

    output_path = convert_to_image_pdf(args, paths, pdf_path)
    log.info("Saved %s", output_path)


def gen_arg_groups(args):
    local_paths = []
    for path in args.paths:
        if path.startswith("http"):
            path = web.download_url(args, path)
            if path:
                local_paths.append(os.path.realpath(path))
            else:
                log.error("Could not save URL %s", path)
        else:
            local_paths.append(os.path.realpath(path))

    individual_files = []
    for path in local_paths:
        if os.path.isdir(path):
            dir_image_paths = file_utils.rglob(
                str(path), args.ext or DEFAULT_EXTENSIONS, getattr(args, "exclude", None)
            )[0]
            if dir_image_paths:
                yield dir_image_paths
            else:
                log.warning("No images found in %s", path)
        elif path_utils.ext(path) in consts.ARCHIVE_EXTENSIONS:
            archive_dir = processes.unar_delete(path)
            archive_image_paths = file_utils.rglob(str(archive_dir), DEFAULT_EXTENSIONS, quiet=True)[0]
            if archive_image_paths:
                yield archive_image_paths
            else:
                log.warning("No images found from extracted archive in %s", archive_dir)
        else:
            individual_files.append(path)
    if individual_files:
        yield individual_files


def images_to_pdf():
    args = parse_args()

    for group_paths in gen_arg_groups(args):
        try:
            process_paths(args, group_paths)
        except Exception:
            print(group_paths)
            raise
