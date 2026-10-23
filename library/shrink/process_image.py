import argparse, os, shlex, subprocess
from pathlib import Path

from library import usage
from library.data import imagemagick_errors
from library.utils import arggroups, argparse_utils, consts, devices, path_utils, processes, shell_utils, web
from library.utils.log_utils import log
from library.utils.shell_utils import gen_paths
from library.utils.web import WebPath

_IMAGE_COMMAND_SUCCESS = object()


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_image)
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


def _process_image_archive(args, path):
    if args.simulate:
        log.info("Extracting images %s", path)
        return None
    archive_dir, _ = processes.unar_delete(path)
    image_paths = shell_utils.rglob(str(archive_dir), consts.IMAGE_EXTENSIONS, quiet=True)[0]
    for image_path in image_paths:
        process_path(args, image_path)
    return archive_dir


def _run_image_command(args, path, output_path, command):
    try:
        processes.cmd(
            *command,
            ignore_regexps=[
                imagemagick_errors.ignore_error,
                imagemagick_errors.unsupported_error,
                imagemagick_errors.file_error,
            ],
            limit_ram=True,
            nice=8,
        )
    except subprocess.CalledProcessError as excinfo:
        error_log = excinfo.stderr.splitlines()
        is_unsupported = any(imagemagick_errors.unsupported_error.match(l) for l in error_log)
        is_file_error = any(imagemagick_errors.file_error.match(l) for l in error_log)
        is_env_error = any(imagemagick_errors.environment_error.match(l) for l in error_log)

        if is_env_error:
            raise
        if is_unsupported:
            output_path.unlink(missing_ok=True)
            return str(path)
        if is_file_error:
            if args.delete_unplayable:
                path.unlink()
            return None
    return _IMAGE_COMMAND_SUCCESS


def _finish_image(args, path, output_path, original_stats):
    if not output_path.exists():
        return str(path) if path.exists() else None

    output_stats = output_path.stat()
    too_large = (
        args.delete_larger
        and not getattr(args, "delete_original", False)
        and output_stats.st_size > original_stats.st_size
    )
    if output_stats.st_size == 0 or too_large:
        output_path.unlink()
        return str(path)

    if args.delete_larger or getattr(args, "delete_original", False):
        path.unlink()
    os.utime(output_path, (original_stats.st_atime, original_stats.st_mtime))
    return str(output_path)


def process_path(args, path) -> str | None:
    output_path = web.gen_output_path(args, path, target_extension=".avif")

    if path_utils.ext(path) in consts.ARCHIVE_EXTENSIONS:
        archive_result = _process_image_archive(args, path)
        if not args.simulate:
            return archive_result

    if args.simulate:
        command = ["magick", str(path), "-resize", f"{args.max_image_width}x{args.max_image_height}>", str(output_path)]
        print(shlex.join(command))
        return str(path)

    path, output_path = devices.clobber(args, path, output_path)
    if path is None:
        return output_path

    path = WebPath(path)
    output_path = Path(output_path)

    if not args.simulate:
        output_path.parent.mkdir(exist_ok=True, parents=True)
    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)

    command = ["magick", str(path), "-resize", f"{args.max_image_width}x{args.max_image_height}>", str(output_path)]

    try:
        original_stats = path.stat()
    except FileNotFoundError:
        log.error("File not found: %s", path)
        return None

    result = _run_image_command(args, path, output_path, command)
    if result is not _IMAGE_COMMAND_SUCCESS:
        return result
    return _finish_image(args, path, output_path, original_stats)


def process_image():
    args = parse_args()

    for raw_path in gen_paths(args, consts.IMAGE_EXTENSIONS | consts.ARCHIVE_EXTENSIONS):
        path = raw_path
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise
