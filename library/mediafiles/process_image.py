import argparse, os, shlex, subprocess
from pathlib import Path

from library import usage
from library.data import imagemagick_errors
from library.utils import arggroups, argparse_utils, consts, devices, file_utils, path_utils, processes, web
from library.utils.file_utils import gen_paths
from library.utils.log_utils import log
from library.utils.web import WebPath


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_image)
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
    parser.add_argument("--clean-path", action=argparse.BooleanOptionalAction, default=False, help="Clean output path")
    parser.add_argument(
        "--hide-deleted",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exclude non-existent files from processing",
    )
    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-dest")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


def process_path(args, path) -> str | None:
    output_path = web.gen_output_path(args, path, target_extension=".avif")

    ext = path_utils.ext(path)

    if ext in consts.ARCHIVE_EXTENSIONS:
        if args.simulate:
            log.info("Extracting images %s", path)
        else:
            archive_dir = processes.unar_delete(path)
            image_paths = file_utils.rglob(str(archive_dir), consts.IMAGE_EXTENSIONS, quiet=True)[0]
            for p in image_paths:
                process_path(args, p)
            return archive_dir

    path, output_path = devices.clobber(args, path, output_path)
    if path is None:
        return output_path

    path = WebPath(path)
    output_path = Path(output_path)

    output_path.parent.mkdir(exist_ok=True, parents=True)
    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)

    command = ["magick", str(path), "-resize", f"{args.max_image_width}x{args.max_image_height}>", str(output_path)]

    if args.simulate:
        print(shlex.join(command))
        return str(path)

    try:
        original_stats = path.stat()
    except FileNotFoundError:
        log.error("File not found: %s", path)
        return None

    try:
        processes.cmd(
            *command,
            ignore_regexps=[
                imagemagick_errors.ignore_error,
                imagemagick_errors.unsupported_error,
                imagemagick_errors.file_error,
            ],
            limit_ram=True,
        )
    except subprocess.CalledProcessError as e:
        error_log = e.stderr.splitlines()
        is_unsupported = any(imagemagick_errors.unsupported_error.match(l) for l in error_log)
        is_file_error = any(imagemagick_errors.file_error.match(l) for l in error_log)
        is_env_error = any(imagemagick_errors.environment_error.match(l) for l in error_log)

        if is_env_error:
            raise
        elif is_unsupported:
            output_path.unlink(missing_ok=True)  # Remove transcode attempt, if any
            return str(path)
        elif is_file_error:
            if args.delete_unplayable:
                path.unlink()
            return None

    if not output_path.exists():
        return str(path) if path.exists else None

    output_stats = output_path.stat()
    if output_stats.st_size == 0 or (args.delete_larger and output_stats.st_size > original_stats.st_size):
        output_path.unlink()  # Remove transcode
        return str(path)

    if args.delete_larger:
        path.unlink()  # Remove original
    os.utime(output_path, (original_stats.st_atime, original_stats.st_mtime))

    return str(output_path)


def process_image():
    args = parse_args()

    for path in gen_paths(args, consts.IMAGE_EXTENSIONS | consts.ARCHIVE_EXTENSIONS):
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise
