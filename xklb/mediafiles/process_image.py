import argparse, os, shlex, subprocess
from pathlib import Path

from xklb import usage
from xklb.data import imagemagick_errors
from xklb.utils import arggroups, argparse_utils, consts, devices, processes, web
from xklb.utils.arg_utils import gen_paths
from xklb.utils.log_utils import log
from xklb.utils.web import WebPath


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_image)
    parser.add_argument("--delete-unplayable", action="store_true")
    parser.add_argument("--max-image-height", type=int, default=2400)
    parser.add_argument("--max-image-width", type=int, default=2400)
    parser.add_argument(
        "--delete-original", action=argparse.BooleanOptionalAction, default=True, help="Delete source files"
    )
    parser.add_argument("--clean-path", action=argparse.BooleanOptionalAction, default=True, help="Clean output path")
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


def process_path(args, path):
    output_path = web.gen_output_path(args, path, target_extension=".avif")

    path, output_path = devices.clobber(args, path, output_path)
    if path is None:
        return output_path

    path = WebPath(path)
    output_path = Path(output_path)

    output_path.parent.mkdir(exist_ok=True, parents=True)
    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)

    command = [
        "magick",
        str(path),
        "-resize",
        f"{args.max_image_width}x{args.max_image_height}>",
        str(output_path),
    ]

    if args.simulate:
        print(shlex.join(command))
        return path

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
            return path
        elif is_file_error:
            if args.delete_unplayable:
                path.unlink()
            return None

    if not Path(output_path).exists() or output_path.stat().st_size == 0:
        output_path.unlink()  # Remove transcode
        return path

    if original_stats.st_size > 0 and output_path.stat().st_size > original_stats.st_size:
        output_path.unlink()  # Remove transcode
        return path
    else:
        if args.delete_original:
            path.unlink()  # Remove original
        os.utime(output_path, (original_stats.st_atime, original_stats.st_mtime))

    return output_path


def process_image():
    args = parse_args()

    for path in gen_paths(args, consts.IMAGE_EXTENSIONS):
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_image()
