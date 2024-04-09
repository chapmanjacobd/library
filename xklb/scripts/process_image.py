import argparse, subprocess
from pathlib import Path

from xklb import usage
from xklb.utils import objects, processes, web
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library process-image", usage=usage.process_image)
    parser.add_argument("--delete-unplayable", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def process_path(path, delete_broken=False):
    if path.startswith("http"):
        output_path = Path(web.url_to_local_path(path)).with_suffix(".avif")
    else:
        output_path = Path(path).with_suffix(".avif")

    path = Path(path)

    if path == output_path:
        output_path = Path(path).with_suffix(".resized.avif")
        if path == output_path:
            raise RuntimeError("Input and output files must have different names")

    try:
        processes.cmd(
            ["magick", "mogrify", "-define", "preserve-timestamp=true", "-resize", "2400>", "-format", "avif", path]
        )
    except subprocess.CalledProcessError:
        log.exception("Could not transcode: %s", path)
        if delete_broken:
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
            process_path(path, delete_broken=args.delete_unplayable)
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_image()
