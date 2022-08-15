import argparse
import sys

from xklb.fs_actions import filesystem, listen, watch
from xklb.fs_extract import main as extract
from xklb.subtitle import main as subtitle
from xklb.tube_actions import tube_list, tube_listen, tube_watch
from xklb.tube_extract import tube_add, tube_update
from xklb.utils import Subcommand, log


def lb(args=None):
    if args:
        sys.argv[2:] = args

    parser = argparse.ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers()
    xr = subparsers.add_parser("extract", aliases=["xr"], add_help=False)
    xr.set_defaults(func=extract)
    sub = subparsers.add_parser("subtitle", aliases=["sub"], add_help=False)
    sub.set_defaults(func=subtitle)

    lt = subparsers.add_parser(Subcommand.listen, aliases=["lt"], add_help=False)
    lt.set_defaults(func=listen)
    wt = subparsers.add_parser(Subcommand.watch, aliases=["wt"], add_help=False)
    wt.set_defaults(func=watch)
    fs = subparsers.add_parser(Subcommand.filesystem, aliases=["fs"], add_help=False)
    fs.set_defaults(func=filesystem)

    tlist = subparsers.add_parser("tubelist", aliases=["playlist", "playlists"], add_help=False)
    tlist.set_defaults(func=tube_list)
    ta = subparsers.add_parser("tubeadd", aliases=["ta"], add_help=False)
    ta.set_defaults(func=tube_add)
    tu = subparsers.add_parser("tubeupdate", aliases=["tu"], add_help=False)
    tu.set_defaults(func=tube_update)

    tw = subparsers.add_parser(Subcommand.tubewatch, aliases=["tw", "entries"], add_help=False)
    tw.set_defaults(func=tube_watch)
    tl = subparsers.add_parser(Subcommand.tubelisten, aliases=["tl"], add_help=False)
    tl.set_defaults(func=tube_listen)

    parser.add_argument("--version", "-V", action="store_true")
    args, _unk = parser.parse_known_args(args)
    if args.version:
        from xklb import __version__

        return print(__version__)

    if len(sys.argv) > 1:
        del sys.argv[1]

    log.info(sys.argv)
    if hasattr(args, "func"):
        args.func()
    else:
        try:
            print("Subcommand", sys.argv[1], "not found")
        except:
            print("Invalid args. I see:", sys.argv)

        parser.print_help()


def main():
    lb()


if __name__ == "__main__":
    main()
