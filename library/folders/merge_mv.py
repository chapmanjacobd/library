import argparse, concurrent.futures, os, shutil
from pathlib import Path

from library import usage
from library.folders import filter_src
from library.folders.filter_src import track_moved
from library.utils import arggroups, argparse_utils, devices, file_utils, path_utils
from library.utils.file_utils import rglob_gen
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
                    not args.simulate,
                    not args.timeout_size,
                    not args.limit,
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
                    append_basename = destination.endswith(os.sep) or os.path.isdir(destination)
                if append_basename:
                    file_dest = os.path.join(file_dest, path_utils.basename(source))
                    log.debug("file append basename %s", file_dest)

            src, dest = devices.clobber(args, source, file_dest)
            if src:
                yield src, dest


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


def merge_cp():
    merge_mv({"copy": True, "file_over_file": "skip-hash rename-dest"})


def rel_mv():
    merge_mv({"relative": True})


def rel_cp():
    merge_mv({"relative": True, "copy": True, "file_over_file": "skip-hash rename-dest"})
