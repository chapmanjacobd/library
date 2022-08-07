import argparse
import sys

from xklb.fs_actions import filesystem, listen, watch
from xklb.fs_extract import main as extract
from xklb.tube_actions import tube_listen, tube_watch
from xklb.tube_extract import tube_add
from xklb.utils import Subcommand, log


def lb(args=None):
    parser = argparse.ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers()
    lt = subparsers.add_parser(Subcommand.listen, aliases=["lt"], add_help=False)
    lt.set_defaults(func=listen)

    wt = subparsers.add_parser(Subcommand.watch, aliases=["wt"], add_help=False)
    wt.set_defaults(func=watch)

    xr = subparsers.add_parser("extract", aliases=["xr"], add_help=False)
    xr.set_defaults(func=extract)

    fs = subparsers.add_parser(Subcommand.filesystem, aliases=["p"], add_help=False)
    fs.set_defaults(func=filesystem)

    ta = subparsers.add_parser("tube_add", aliases=["ta"], add_help=False)
    ta.set_defaults(func=tube_add)

    tw = subparsers.add_parser(Subcommand.tubewatch, aliases=["tw"], add_help=False)
    tw.set_defaults(func=tube_watch)

    tl = subparsers.add_parser(Subcommand.tubelisten, aliases=["tl"], add_help=False)
    tl.set_defaults(func=tube_listen)

    args, _unk = parser.parse_known_args(args)
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
