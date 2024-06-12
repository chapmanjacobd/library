import os, shutil, sys

from xklb import usage
from xklb.utils import arggroups, argparse_utils, devices, file_utils, path_utils


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


def mmv_file(args, source, destination):
    if args.simulate:
        print(source)
        print("-->", destination)
    else:
        file_utils.rename_move_file(source, destination)


def mcp_file(args, source, destination):
    if args.simulate:
        print(source)
        print("==>", destination)
    else:
        shutil.copy2(source, destination)


def mmv_folders(args, mv_fn, sources, destination):
    destination = os.path.realpath(destination)

    if args.bsd:
        # preserve trailing slash
        sources = (os.path.realpath(s) + (os.sep if s.endswith(os.sep) else "") for s in sources)
    else:
        sources = (os.path.realpath(s) for s in sources)

    for source in sources:
        if os.path.isdir(source):
            for p in sorted(
                file_utils.rglob(source, args.ext or None)[0], key=lambda s: (s.count(os.sep), len(s), s), reverse=False
            ):
                file_dest = destination
                if args.parent or (args.bsd and not source.endswith(os.sep)):  # use BSD behavior
                    file_dest = os.path.join(file_dest, os.path.basename(source))
                file_dest = os.path.join(file_dest, os.path.relpath(p, source))

                p, file_dest = devices.clobber(args, p, file_dest)
                if p:
                    mv_fn(args, p, file_dest)

        else:
            file_dest = destination
            if args.parent:
                file_dest = os.path.join(file_dest, path_utils.parent(source))
            if path_utils.is_folder_dest(source, file_dest):
                file_dest = os.path.join(file_dest, os.path.basename(source))

            source, file_dest = devices.clobber(args, source, file_dest)
            if source:
                mv_fn(args, source, file_dest)


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
