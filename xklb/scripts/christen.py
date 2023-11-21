import argparse, shutil
from os import fsdecode
from pathlib import Path

from xklb import usage
from xklb.utils import objects, path_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library christen", usage=usage.christen)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--dot-space", action="store_true")
    parser.add_argument("--case-insensitive", action="store_true")
    parser.add_argument("--lowercase-folders", action="store_true")
    parser.add_argument("--overwrite", "-f", action="store_true")
    parser.add_argument("--run", "-r", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def rename_path(args, base, b) -> None:
    fixed = path_utils.clean_path(
        b,
        dot_space=args.dot_space,
        case_insensitive=args.case_insensitive,
        lowercase_folders=args.lowercase_folders,
    )

    if b != fixed.encode():
        printable_p = b.decode("utf-8", "backslashreplace")
        if args.run:
            p = base / fsdecode(b)
            if not p.is_file():
                log.info("Skipping non-file. %s", printable_p)
                return
            if p.is_symlink():
                log.info("Skipping symlink. %s", printable_p)
                return
            try:
                fixed = base / fixed
                fixed.parent.mkdir(parents=True, exist_ok=True)

                if fixed.exists() and not args.overwrite:
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
            print()


def christen() -> None:
    args = parse_args()

    for path in args.paths:
        base = Path(path).resolve()
        log.info("[%s]: Processing subfolders...", base)
        subpaths = sorted((bytes(p.relative_to(base)) for p in base.rglob("*")), key=len, reverse=True)
        for p in subpaths:
            rename_path(args, base, p)

    print(
        r"""
    You may want to run bfs to remove nested empty folders:

        yes | bfs -type d -exec bfs -f {} -not -type d -exit 1 \; -prune -ok bfs -f {} -type d -delete \;
        """,
    )


if __name__ == "__main__":
    christen()
