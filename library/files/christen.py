import argparse, shutil
from os import fsdecode, fsencode
from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, file_utils, path_utils
from library.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.christen)
    parser.add_argument("--dot-space", action="store_true")
    parser.add_argument("--case-insensitive", action="store_true")
    parser.add_argument("--lowercase-folders", action="store_true")
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--run", "-r", action="store_true")
    arggroups.debug(parser)

    parser.add_argument("--exclude", "-E", nargs="+", action="extend", default=[])

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

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
                log.info("Skipping non-file: %s", printable_p)
                return
            if p.is_symlink():
                log.info("Skipping symlink: %s", printable_p)
                return
            try:
                fixed = base / fixed
                fixed.parent.mkdir(parents=True, exist_ok=True)

                if fixed.exists() and not args.force:
                    raise FileExistsError

                p.rename(fixed)
            except FileNotFoundError:
                log.warning("FileNotFound: %s", printable_p)
            except FileExistsError:
                log.warning("Destination file already exists: %s", fixed)
            except shutil.Error as e:
                log.warning("[%s]: %s", e, printable_p)
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
        subpaths = sorted(
            (fsencode(p) for p in file_utils.rglob(str(base), args.ext or None, args.exclude)[0]), key=len, reverse=True
        )
        for p in subpaths:
            rename_path(args, base, p)

        path_utils.bfs_removedirs(base)
