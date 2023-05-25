import argparse, sys

from xklb import utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library cluster-sort",
        usage="""library cluster-sort [input_path | stdin] [output_path | stdout]

    Group lines of text into sorted output
""",
    )
    parser.add_argument("--model", help="Use a specific spaCy model")
    parser.add_argument("--groups", action="store_true", help="Show groups")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("input_path", nargs="?", type=argparse.FileType("r"), default=sys.stdin)
    parser.add_argument("output_path", nargs="?", type=argparse.FileType("w"), default=sys.stdout)
    args = parser.parse_args()

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def cluster_sort() -> None:
    args = parse_args()

    lines = args.input_path.readlines()
    groups = utils.cluster_paths(args, lines)
    groups = sorted(groups, key=lambda d: (len(d["grouped_paths"]), -len(d["common_prefix"])))

    if args.groups:
        from rich import print

        print(groups)
    else:
        lines = utils.flatten(d["grouped_paths"] for d in groups)
        args.output_path.writelines(lines)


if __name__ == "__main__":
    cluster_sort()
