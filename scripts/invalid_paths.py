import argparse, shutil
from pathlib import Path

import ftfy

from xklb import utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def rename_invalid_paths() -> None:
    args = parse_args()

    for path in args.paths:
        log.info(path)
        for p in sorted([str(p) for p in Path(path).rglob("*")], key=len, reverse=True):
            fixed = ftfy.fix_text(p, uncurl_quotes=False).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "")
            if p != fixed:
                try:
                    Path(fixed).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(p, fixed)
                except FileNotFoundError:
                    log.warning("FileNotFound. %s", p)
                else:
                    log.info(fixed)


if __name__ == "__main__":
    rename_invalid_paths()
