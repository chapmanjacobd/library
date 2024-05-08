import argparse, os, shlex, subprocess
from pathlib import Path

from xklb import usage
from xklb.data import imagemagick_errors
from xklb.utils import arggroups, argparse_utils, path_utils, processes, web
from xklb.utils.arg_utils import gen_paths
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library process-image", usage=usage.process_image)
    arggroups.simulate(parser)
    parser.add_argument("--delete-unplayable", action="store_true")

    parser.add_argument("--max-image-height", type=int, default=2400)
    parser.add_argument("--max-image-width", type=int, default=2400)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    return args


def process_path(args, path):
    if str(path).startswith("http"):
        output_path = Path(web.url_to_local_path(path))
    else:
        output_path = Path(path)
    output_path = Path(path_utils.clean_path(bytes(output_path.with_suffix(".avif"))))

    path = Path(path)
    if path == output_path:
        output_path = Path(path).with_suffix(".r.avif")
        if path == output_path:
            log.error("Input and output files must have different names %s", path)
            return path

    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)
        output_path.parent.mkdir(exist_ok=True, parents=True)

    command = [
        "magick",
        "convert",
        "-resize",
        f"{args.max_image_width}x{args.max_image_height}>",
        str(path),
        str(output_path),
    ]

    if args.simulate:
        print(shlex.join(command))
        return path

    original_stats = path.stat()

    try:
        processes.cmd(
            *command,
            ignore_regexps=[
                imagemagick_errors.ignore_error,
                imagemagick_errors.unsupported_error,
                imagemagick_errors.image_error,
            ],
        )
    except subprocess.CalledProcessError as e:
        error_log = e.stderr.splitlines()
        is_unsupported = any(imagemagick_errors.unsupported_error.match(l) for l in error_log)
        is_image_error = any(imagemagick_errors.image_error.match(l) for l in error_log)
        is_env_error = any(imagemagick_errors.environment_error.match(l) for l in error_log)

        if is_unsupported:
            output_path.unlink(missing_ok=True)  # Remove transcode attempt, if any
            return path
        elif args.delete_unplayable and not is_env_error and is_image_error:
            path.unlink()
            return None
        else:
            raise

    if not Path(output_path).exists() or output_path.stat().st_size == 0:
        output_path.unlink()  # Remove transcode
        return path

    if output_path.stat().st_size > path.stat().st_size:
        output_path.unlink()  # Remove transcode
        return path
    else:
        path.unlink()  # Remove original
        os.utime(output_path, (original_stats.st_atime, original_stats.st_mtime))

    return output_path


def process_image():
    args = parse_args()

    for path in gen_paths(args):
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_image()
