import os, shutil, sys

from xklb import usage
from xklb.utils import arggroups, argparse_utils, devices, file_utils, path_utils
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.merge_mv)
    parser.add_argument("--copy", "--cp", "-c", action="store_true", help="Copy instead of move")
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser, destination=True)
    parser.add_argument("destination", help="Destination directory")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


class FolderExistsError(Exception):
    pass


def mmv_file(args, source, destination, copy=False):
    if args.simulate:
        cmd_args = ["cp" if copy else "mv"]
        if args.replace is None:
            cmd_args.append("--interactive")
        elif args.replace is False:
            cmd_args.append("--no-clobber")

        print(*cmd_args, source, destination)
    else:
        if source == destination:
            log.info("Destination is the same as source %s", destination)
            return

        if os.path.exists(destination):
            if os.path.isdir(destination):
                # cannot replace directory with file of same name: move the file inside the folder instead
                # TODO: expose flags to enable or disable this
                destination = os.path.join(destination, os.path.basename(destination))
                return mmv_file(args, source, destination, copy=copy)

        if os.path.exists(destination):
            if os.path.isdir(destination):
                raise FolderExistsError
            destination = devices.clobber(args, source, destination)
        else:
            parent_dir = os.path.dirname(destination)
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except (FileExistsError, NotADirectoryError, FileNotFoundError):
                # NotADirectoryError: a file exists _somewhere_ in the path hierarchy
                # Windows gives FileNotFoundError instead
                while not os.path.exists(parent_dir):
                    parent_dir = os.path.dirname(parent_dir)  # we keep going up until we find a valid file

                log.warning("FileExistsError: A file exists instead of a folder %s", parent_dir)
                # TODO: expose flags for granular control: force interactive, replace, no-replace
                parent_dir = devices.clobber(args, source, parent_dir, allow_renames=False)
                if parent_dir is None:
                    return
                os.makedirs(os.path.dirname(destination), exist_ok=True)  # use original destination parent

        if destination is None:
            return
        if copy:
            shutil.copy2(source, destination)
        else:
            file_utils.rename_move_file(source, destination)

    return destination


def mcp_file(*args, **kwargs):
    return mmv_file(*args, **kwargs, copy=True)


def mmv_folders(args, mv_fn, sources, destination):
    destination = os.path.realpath(destination)

    sources = (os.path.realpath(s) + (os.sep if s.endswith(os.sep) else "") for s in sources)  # preserve trailing slash
    for source in sources:
        if os.path.isdir(source):
            for p in file_utils.rglob(source, args.ext or None)[0]:
                cp_dest = destination
                if args.parent is not False and (args.parent or not source.endswith(os.sep)):  # use BSD behavior
                    cp_dest = os.path.join(cp_dest, os.path.basename(source))
                cp_dest = os.path.join(cp_dest, os.path.relpath(p, source))

                mv_fn(args, p, cp_dest)

        else:
            cp_dest = destination
            if args.parent:
                cp_dest = os.path.join(cp_dest, path_utils.parent(source))
            if path_utils.is_folder_dest(source, cp_dest):
                cp_dest = os.path.join(cp_dest, os.path.basename(source))

            mv_fn(args, source, cp_dest)


def merge_mv():
    args = parse_args()

    if args.copy:
        mmv_folders(args, mcp_file, args.paths, args.destination)
    else:
        mmv_folders(args, mmv_file, args.paths, args.destination)
        for p in args.paths:
            if os.path.isdir(p):
                path_utils.bfs_removedirs(p)


def merge_cp():
    sys.argv += ["--copy"]
    merge_mv()
