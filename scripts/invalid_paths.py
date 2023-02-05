import argparse, shutil
from os import fsdecode
from pathlib import Path

from xklb import utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--dot-space", action="store_true")
    parser.add_argument("--overwrite", "-f", action="store_true")
    parser.add_argument("--run", "-r", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def rename_path(args, b):
    fixed = utils.clean_path(b, args.dot_space)

    if b != fixed.encode():
        printable_p = b.decode("utf-8", "backslashreplace")
        if args.run:
            p = Path(fsdecode(b))
            if not p.is_file():
                log.info("Skipping non-file. %s", printable_p)
                return
            if p.is_symlink():
                log.info("Skipping symlink. %s", printable_p)
                return
            try:
                Path(fixed).parent.mkdir(parents=True, exist_ok=True)

                if Path(fixed).exists() and not args.overwrite:
                    raise FileExistsError

                p.rename(fixed)
            except FileNotFoundError:
                log.warning("FileNotFound. %s", printable_p)
            except FileExistsError:
                log.warning("Destination file already exists. %s", fixed)
            except shutil.Error as e:
                log.warning("%s. %s", e, printable_p)
            else:
                log.info(fixed)
        else:
            log.warning(printable_p)
            log.warning(fixed)
            print("")


def rename_invalid_paths() -> None:
    args = parse_args()

    for path in args.paths:
        log.info("[%s]: Processing subfolders...", path)
        subpaths = sorted((bytes(p) for p in Path(path).rglob("*")), key=len, reverse=True)
        for p in subpaths:
            rename_path(args, p)
        # Parallel()(delayed(rename_path)(p) for p in subpaths)  # mostly IO bound

    print(
        r"""
    You may want to run bfs to remove nested empty folders:

        yes | bfs -nohidden -type d -exec bfs -f {} -not -type d -exit 1 \; -prune -ok bfs -f {} -type d -delete \;
        """
    )


if __name__ == "__main__":
    rename_invalid_paths()
