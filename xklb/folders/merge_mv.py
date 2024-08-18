import concurrent.futures, os, shutil
from pathlib import Path

from xklb import usage
from xklb.utils import arggroups, argparse_utils, devices, file_utils, path_utils, processes


def parse_args(defaults_override=None):
    parser = argparse_utils.ArgumentParser(usage=usage.merge_mv)
    parser.add_argument("--copy", "--cp", "-c", action="store_true", help="Copy instead of move")
    parser.add_argument(
        "--modify-depth", "-Dm", "-mD", action=argparse_utils.ArgparseSlice, help="Trim path parts from each source"
    )
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser, destination=True)
    parser.add_argument("destination", help="Destination directory")

    parser.set_defaults(**(defaults_override or {}))
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


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


def gen_src_dest(args, sources, destination):
    for source in sources:
        if os.path.isdir(source):
            for p in file_utils.rglob_gen(source, args.ext or None):
                if args.timeout_size:
                    processes.sizeout(args.timeout_size, Path(p).stat().st_size)

                file_dest = destination
                if args.parent or (args.bsd and not source.endswith(os.sep)):  # use BSD behavior
                    file_dest = os.path.join(file_dest, os.path.basename(source))

                relpath = os.path.relpath(p, source)
                if args.modify_depth:
                    rel_p = Path(relpath)
                    parts = rel_p.parent.parts[args.modify_depth]
                    relpath = os.path.join(*parts, rel_p.name)

                file_dest = os.path.join(file_dest, relpath)

                src, dest = devices.clobber(args, p, file_dest)
                if src:
                    yield src, dest

        else:  # source is a file
            if args.timeout_size:
                processes.sizeout(args.timeout_size, Path(source).stat().st_size)

            file_dest = destination
            if args.parent:
                file_dest = os.path.join(file_dest, path_utils.parent(source))
            if path_utils.is_folder_dest(source, file_dest):
                file_dest = os.path.join(file_dest, os.path.basename(source))

            src, dest = devices.clobber(args, source, file_dest)
            if src:
                yield src, dest


def mmv_folders(args, mv_fn, sources, destination):
    destination = os.path.realpath(destination)

    if args.bsd:
        # preserve trailing slash
        sources = (os.path.realpath(s) + (os.sep if s.endswith(os.sep) else "") for s in sources)
    else:
        sources = (os.path.realpath(s) for s in sources)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as ex:
        for f in (ex.submit(mv_fn, args, src, dest) for src, dest in gen_src_dest(args, sources, destination)):
            f.result()


def merge_mv(defaults_override=None):
    args = parse_args(defaults_override)

    if args.copy:
        mmv_folders(args, mcp_file, args.paths, args.destination)
    else:
        mmv_folders(args, mmv_file, args.paths, args.destination)
        for p in args.paths:
            if os.path.isdir(p):
                path_utils.bfs_removedirs(p)


def merge_cp():
    merge_mv({"copy": True})
