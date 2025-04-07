import argparse, concurrent.futures, os, shutil
from fnmatch import fnmatch
from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, file_utils, path_utils, printing, processes, strings
from library.utils.log_utils import log


def parse_args(defaults_override=None):
    parser = argparse_utils.ArgumentParser(usage=usage.merge_mv)
    parser.add_argument("--copy", "--cp", "-c", action="store_true", help=argparse.SUPPRESS)
    arggroups.mmv_folders(parser)
    parser.add_argument(
        "--clobber", "--overwrite", action="store_true", help="Shortcut for --file-over-file delete-dest"
    )
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser, destination=True)
    parser.add_argument("destination", help="Destination directory")

    parser.set_defaults(**(defaults_override or {}))
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.mmv_folders_post(args)
    if not any([args.dest_bsd, args.dest_file, args.dest_folder]):
        args.destination_folder = True

    if args.clobber:
        if args.file_over_file[-1] == "rename-dest":
            args.file_over_file[-1] = "delete-dest"
        else:
            args.file_over_file = arggroups.file_over_file("delete-dest")

    return args


MOVED_COUNT = 0
MOVED_SIZE = 0


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


@track_moved
def mmv_file(args, source, destination):
    if args.simulate:
        print(source)
        print("-->", destination)
    else:
        file_utils.rename_move_file(source, destination)
        log.debug("moved %s\t%s", source, destination)


@track_moved
def mcp_file(args, source, destination):
    if args.simulate:
        print(source)
        print("==>", destination)
    else:
        out = shutil.copy2(source, destination)
        log.debug("copied %s\t%s", source, out)


def filter_src(args, path):
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return False
    if args.sizes and not args.sizes(stat.st_size):
        return False

    if any(fnmatch(path, s) for s in args.exclude):
        return False

    if args.timeout_size and processes.sizeout(args.timeout_size, stat.st_size):
        print(f"\nReached sizeout... ({args.timeout_size})")
        raise SystemExit(124)
    elif args.limit and MOVED_COUNT >= args.limit:
        print(f"\nReached file moved limit... ({args.limit})")
        raise SystemExit(124)

    return True


def mmv_folders(args, mv_fn, sources, destination, shortcut_allowed=False):
    destination = os.path.realpath(destination) + (os.sep if destination.endswith(os.sep) else "")

    if args.bsd:
        # preserve trailing slash
        sources = (os.path.realpath(s) + (os.sep if s.endswith(os.sep) else "") for s in sources)
    else:
        sources = (os.path.realpath(s) for s in sources)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as ex:
        for f in (
            ex.submit(mv_fn, args, src, dest)
            for src, dest in path_utils.gen_src_dest(args, sources, destination, shortcut_allowed=shortcut_allowed)
        ):
            f.result()


def merge_mv(defaults_override=None):
    args = parse_args(defaults_override)

    if args.copy:
        mmv_folders(args, mcp_file, args.paths, args.destination)
    else:
        mmv_folders(args, mmv_file, args.paths, args.destination, shortcut_allowed=True)
        for p in args.paths:
            if os.path.isdir(p):
                path_utils.bfs_removedirs(p)


def merge_cp():
    merge_mv({"copy": True, "file_over_file": "skip-hash rename-dest"})


def rel_mv():
    merge_mv({"relative": True})


def rel_cp():
    merge_mv({"relative": True, "copy": True, "file_over_file": "skip-hash rename-dest"})
