import os, shutil, sys

from xklb import usage
from xklb.utils import arggroups, argparse_utils, devices, file_utils, path_utils
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.merge_mv)
    parser.add_argument("--copy", "--cp", "-c", action="store_true", help="Copy instead of move")
    parser.add_argument("--simulate", "--dry-run", action="store_true", help="Dry run")
    arggroups.clobber(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser, destination=True)
    parser.add_argument("destination", help="Destination directory")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def mmv_file(args, source, destination):
    src_dest = [source, destination]
    if args.simulate:
        print(*args.cp_args, *src_dest)
    else:
        if source == destination:
            log.info("Destination is the same as source %s", destination)
            return

        if os.path.exists(destination):
            if args.replace is True:
                try:
                    os.unlink(destination)
                except IsADirectoryError:
                    # attempting to replace directory with file of same name: move the file inside folder instead
                    destination = os.path.join(destination, os.path.basename(destination))
                except PermissionError:
                    if os.path.isdir(destination):
                        # Mac OS IsADirectoryError is a PermissionError
                        destination = os.path.join(destination, os.path.basename(destination))
                    else:
                        log.error("PermissionError: skipping %s could not delete %s", source, destination)
                        return
            elif args.replace is False:
                log.warning("not replacing %s", destination)
                return
            elif args.replace is None:
                if devices.confirm("Overwrite file? %s" % destination):
                    os.unlink(destination)
                else:
                    log.warning("not replacing %s", destination)
                    return
        else:
            os.makedirs(os.path.dirname(destination), exist_ok=True)

        if args.copy:
            shutil.copy2(source, destination)
        else:
            file_utils.rename_move_file(source, destination)


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

    sources = (
        os.path.realpath(s) + (os.sep if s.endswith(os.sep) else "") for s in args.paths
    )  # preserve trailing slash
    for source in sources:
        if os.path.isdir(source):
            for p in file_utils.rglob(source, args.ext or None)[0]:
                cp_dest = args.destination
                if not source.endswith(os.sep):  # use BSD behavior
                    cp_dest = os.path.join(cp_dest, os.path.basename(source))
                cp_dest = os.path.join(cp_dest, os.path.relpath(p, source))

                mmv_file(args, p, cp_dest)

            if not args.copy:
                path_utils.bfs_removedirs(source)
        else:
            cp_dest = os.path.join(args.destination, os.path.basename(source))
            mmv_file(args, source, cp_dest)


def merge_cp():
    sys.argv += ["--copy"]
    merge_mv()
