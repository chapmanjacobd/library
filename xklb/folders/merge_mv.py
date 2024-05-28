import os, sys

from xklb import usage
from xklb.utils import arggroups, argparse_utils, file_utils, processes
from xklb.utils.path_utils import bfs_removedirs


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.merge_mv)
    parser.add_argument("--copy", "--cp", "-c", action="store_true", help="Copy files")
    parser.add_argument("--simulate", "--dry-run", action="store_true", help="Dry run")
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser, destination=True)
    parser.add_argument("destination", help="Destination directory")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def mcp_file(args, source, destination):
    src_dest = [source, destination]
    if args.simulate:
        print(*args.cp_args, *src_dest)
    else:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        processes.cmd(*args.cp_args, *src_dest, strict=False, quiet=False, error_verbosity=2)


def cp_args(args):
    cmd_args = ["cp" if args.copy else "mv"]
    if args.replace is None:
        cmd_args.append("--interactive")
    elif args.replace is False:
        cmd_args.append("--no-clobber")

    return cmd_args


def merge_mv():
    args = parse_args()

    args.cp_args = cp_args(args)
    args.destination = os.path.realpath(args.destination)

    sources = (os.path.realpath(s) + ("/" if s.endswith("/") else "") for s in args.paths)  # preserve trailing slash
    for source in sources:
        if os.path.isdir(source):
            for p in file_utils.rglob(source, args.ext or None)[0]:
                cp_dest = args.destination
                if not source.endswith(os.sep):  # use BSD behavior
                    cp_dest = os.path.join(cp_dest, os.path.basename(source))
                cp_dest = os.path.join(cp_dest, os.path.dirname(os.path.relpath(p, source)), os.path.basename(p))

                mcp_file(args, p, cp_dest)
            bfs_removedirs(source)
        else:
            mcp_file(args, source, args.destination)


def merge_cp():
    sys.argv += ["--copy"]
    merge_mv()
