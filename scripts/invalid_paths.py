import argparse, shutil
from pathlib import Path

from xklb import utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--dry-run", "-n", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def rename_path(args, p):
    fixed = utils.clean_path(p)

    if p != fixed:
        if args.dry_run:
            log.warning(p)
            log.warning(fixed)
            print("")
        else:
            try:
                Path(fixed).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(p, fixed)
            except FileNotFoundError:
                log.warning("FileNotFound. %s", p)
            except shutil.Error as e:
                log.warning("%s. %s", e, p)
            else:
                log.info(fixed)


def rename_invalid_paths() -> None:
    args = parse_args()

    for path in args.paths:
        log.info("[%s]: Processing subfolders...", path)
        subpaths = sorted((str(p) for p in Path(path).rglob("*")), key=len, reverse=True)
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
