import argparse, os, subprocess
from pathlib import Path

from natsort import natsorted

from xklb import usage
from xklb.utils import arggroups, argparse_utils, consts, devices, file_utils, path_utils, processes, web
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.images_to_pdf)
    parser.add_argument(
        "--delete-original", action=argparse.BooleanOptionalAction, default=False, help="Delete source files"
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


def convert_to_png(input_path):
    if path_utils.ext(input_path) in consts.PIL_EXTENSIONS:
        return input_path
    else:  # consts.IMAGE_EXTENSIONS - consts.PIL_EXTENSIONS
        return subprocess.run(["magick", input_path, "jpg:-"], stdout=subprocess.PIPE, check=True).stdout


def convert_to_image_pdf(args, image_paths, pdf_path):
    import img2pdf

    # TODO: save to temp location and clobber after
    _, pdf_path = devices.clobber(args, image_paths[0], pdf_path)

    log.debug("Converting %s images to PDF %s", len(image_paths), pdf_path)

    with open(pdf_path, "wb") as f:
        png_paths = [convert_to_png(s) for s in image_paths]
        img2pdf.convert(*png_paths, outputstream=f, rotation=img2pdf.Rotation.ifvalid)

    if args.delete_original:
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
            yield file_utils.rglob(
                str(path), args.ext or consts.IMAGE_EXTENSIONS | consts.PIL_EXTENSIONS, getattr(args, "exclude", None)
            )[0]
        elif path_utils.ext(path) in consts.ARCHIVE_EXTENSIONS:
            archive_dir = processes.unar_delete(path)
            yield file_utils.rglob(str(archive_dir), consts.IMAGE_EXTENSIONS, quiet=True)[0]
        else:
            individual_files.append(path)
    yield individual_files


def images_to_pdf():
    args = parse_args()

    for group_paths in gen_arg_groups(args):
        try:
            process_paths(args, group_paths)
        except Exception:
            print(group_paths)
            raise
