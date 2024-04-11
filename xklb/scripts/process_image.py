import argparse, subprocess
from pathlib import Path

from xklb import usage
from xklb.data import imagemagick_errors
from xklb.utils import arggroups, objects, path_utils, processes, web
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library process-image", usage=usage.process_image)
    parser.add_argument("--delete-unplayable", action="store_true")
    arggroups.debug(parser)

    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def process_path(path, delete_unplayable=False):
    if path.startswith("http"):
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

    try:
        processes.cmd(
            "magick",
            "mogrify",
            "-define",
            "preserve-timestamp=true",
            "-resize",
            "2400>",
            "-format",
            "avif",
            str(path),
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
        elif delete_unplayable and not is_env_error and is_image_error:
            path.unlink()
            return None
        else:
            raise

    if output_path.stat().st_size > path.stat().st_size:
        output_path.unlink()  # Remove transcode
        return path
    else:
        path.unlink()  # Remove original

    return output_path


def process_image():
    args = parse_args()

    for path in args.paths:
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(path, delete_unplayable=args.delete_unplayable)
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_image()
