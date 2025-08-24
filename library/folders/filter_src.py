import os
from fnmatch import fnmatch
from pathlib import Path

from library.utils import printing, processes, strings

MOVED_COUNT = 0
MOVED_SIZE = 0


def filter_src(args, path):
    # REMEMBER to exclude in merge-mv shortcut

    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return False
    if args.move_sizes and not args.move_sizes(stat.st_size):
        return False

    if args.ext and not path.lower().endswith(args.ext):
        return False

    if args.move_exclude and any(fnmatch(path, s) for s in args.move_exclude):
        return False

    if args.move_include and not any(fnmatch(path, s) for s in args.move_include):
        return False

    if args.timeout_size and processes.sizeout(args.timeout_size, stat.st_size):
        print(f"\nReached sizeout... ({args.timeout_size})")
        raise SystemExit(124)
    elif args.move_limit and MOVED_COUNT >= args.move_limit:
        print(f"\nReached file move limit... ({args.move_limit})")
        raise SystemExit(124)

    return True


def print_stats(args, dest_path=None, file_size=None):
    file_plural = lambda x: "files" if x > 1 else "file"
    pr = print if args.simulate else printing.print_overwrite

    msg = [
        str(MOVED_COUNT),
        " ",
        file_plural(MOVED_COUNT),
        " ",
        "copied" if args.copy else "moved",
        " ",
        f"({strings.file_size(MOVED_SIZE)})",
    ]
    if dest_path:
        msg.append(f"; {dest_path} ({strings.file_size(file_size)})")

    pr("".join(msg))


def track_moved(func):
    def wrapper(*args, **kwargs):
        if args[0].verbose == 0:
            func(*args, **kwargs)
        else:
            global MOVED_COUNT, MOVED_SIZE
            try:
                file_size = Path(args[1]).stat().st_size
            except FileNotFoundError:
                file_size = 0

            if not args[0].simulate:
                print_stats(args[0], args[2], file_size)
            try:
                func(*args, **kwargs)
                MOVED_SIZE += file_size
                MOVED_COUNT += 1
            finally:
                print_stats(args[0])

    return wrapper
