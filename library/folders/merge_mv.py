import concurrent.futures, os, shutil
from pathlib import Path

from library import usage
from library.folders import filter_src
from library.folders.filter_src import track_moved
from library.utils import arggroups, argparse_utils, devices, file_utils, path_utils
from library.utils.file_utils import rglob_gen
from library.utils.log_utils import log


def parse_args(defaults_override=None):
    parser = argparse_utils.ArgumentParser(usage=usage.merge_mv)
    arggroups.mmv_folders(parser)
    parser.add_argument(
        "--move-sizes",
        "--sizes",
        "--size",
        "-S",
        action="append",
        help="""Constrain files moved by file size (uses the same syntax as fd-find)
-S 6           # 6 MB exactly (not likely)
-S-6           # less than 6 MB
-S+6           # more than 6 MB
-S 6%%10       # 6 MB ±10 percent (between 5 and 7 MB)
-S+5GB -S-7GB  # between 5 and 7 GB""",
    )
    parser.add_argument("--move-limit", "--limit", "-n", "-l", "-L", type=int, help="Limit number of files transferred")
    parser.add_argument(
        "--move-exclude",
        "--exclude",
        "-E",
        nargs="+",
        action="extend",
        default=[],
        help="""Exclude files via fnmatch
-E '*/.tmp/*' -E '*sad*'  # path must not match neither /.tmp/ nor sad """,
    )
    parser.add_argument(
        "--move-include",
        "-I",
        nargs="+",
        action="extend",
        default=[],
        help="""Include files via fnmatch
-I '*/.tmp/*' -I '*sad*'  # path must match either /.tmp/ or sad """,
    )
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

    if args.clobber:
        if args.file_over_file[-1] == "rename-dest":
            args.file_over_file[-1] = "delete-dest"
        else:
            args.file_over_file = arggroups.file_over_file("delete-dest")

    return args


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


def gen_src_dest(args, sources, destination, shortcut_allowed=False):
    for source in sources:
        if args.relative_to:  # modify the destination for each source
            source_destination = path_utils.gen_rel_path(source, destination, args.relative_to)
        else:
            source_destination = destination

        if os.path.isdir(source):
            folder_dest = source_destination
            if not args.relative_to:
                if args.parent or (args.bsd and not source.endswith(os.sep)):  # use BSD behavior
                    folder_dest = os.path.join(folder_dest, path_utils.basename(source))
                    log.debug("folder parent %s", folder_dest)

            # if no conflict, use shortcut
            if all(
                [
                    shortcut_allowed,
                    not args.ext,
                    not args.simulate,
                    not args.timeout_size,
                    not args.move_limit,
                    not args.move_sizes,
                    not args.move_exclude,
                    not args.move_include,
                    not args.modify_depth,
                    not os.path.exists(folder_dest),
                ]
            ):
                log.debug("taking shortcut")
                try:
                    parent = os.path.dirname(folder_dest)
                    if not os.path.exists(parent):
                        log.debug("taking shortcut: making dirs")
                        os.makedirs(parent)
                    os.rename(source, folder_dest)
                except OSError:
                    log.debug("taking shortcut: failed")
                else:
                    log.debug("taking shortcut: success")
                    continue
            # merge source folder with conflict folder/file
            files = rglob_gen(source, args.ext or None)

            for p in files:
                if filter_src.filter_src(args, p) is False:
                    log.debug("rglob-file skipped %s", p)
                    continue

                relpath = os.path.relpath(p, source)
                log.debug("rglob-file relpath %s", relpath)
                if args.modify_depth:
                    rel_p = Path(relpath)
                    parts = rel_p.parent.parts[args.modify_depth]
                    relpath = os.path.join(*parts, rel_p.name)
                    log.debug("rglob-file modify_depth %s %s", parts, relpath)

                file_dest = os.path.join(folder_dest, relpath)
                log.debug("rglob-file file_dest %s", file_dest)

                src, dest = devices.clobber(args, p, file_dest)
                if src:
                    yield src, dest
        else:  # source is a file
            if filter_src.filter_src(args, source) is False:
                log.debug("rglob-file skipped %s", source)
                continue

            file_dest = source_destination
            if not args.relative_to:
                if args.parent:
                    file_dest = os.path.join(file_dest, path_utils.parent(source))
                    log.debug("file parent %s", file_dest)

                if args.dest_file:
                    append_basename = False
                elif args.dest_folder:
                    append_basename = True
                else:  # args.dest_bsd
                    append_basename = (
                        destination.endswith(os.sep) or os.path.isdir(destination) or not os.path.exists(destination)
                    )
                if append_basename:
                    file_dest = os.path.join(file_dest, path_utils.basename(source))
                    log.debug("file append basename %s", file_dest)

            src, dest = devices.clobber(args, source, file_dest)
            if src:
                yield src, dest


def mmv_folders(args, mv_fn, sources, destination, shortcut_allowed=False):
    destination = os.path.realpath(destination) + (os.sep if destination.endswith(os.sep) else "")

    sources = (
        os.path.realpath(s) + (os.sep if str(s).endswith(os.sep) else "")  # preserve trailing slash for --bsd
        for s in sources
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as ex:
        for f in (
            ex.submit(mv_fn, args, src, dest)
            for src, dest in gen_src_dest(args, sources, destination, shortcut_allowed=shortcut_allowed)
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


def move(args, srcs: list, dest: str):
    if getattr(args, "clean_path", True):
        dest = path_utils.clean_path(os.fsencode(dest))
    else:
        dest = str(dest)

    mmv_folders(args, mmv_file, srcs, dest)
    return dest


def merge_cp():
    merge_mv({"copy": True, "file_over_file": "skip-hash rename-dest"})


def rel_mv():
    merge_mv({"relative": True})


def rel_cp():
    merge_mv({"relative": True, "copy": True, "file_over_file": "skip-hash rename-dest"})
