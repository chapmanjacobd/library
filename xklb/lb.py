import argparse
import sys

from xklb.actions import lt, wt
from xklb.extract import main as xr
from xklb.utils import log

def lb(args=None):
    parser = argparse.ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers()
    listen = subparsers.add_parser("listen", aliases=["lt"], add_help=False)
    listen.set_defaults(func=lt)

    watch = subparsers.add_parser("watch", aliases=["wt"], add_help=False)
    watch.set_defaults(func=wt)

    extract = subparsers.add_parser("extract", aliases=["xr"], add_help=False)
    extract.set_defaults(func=xr)

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
