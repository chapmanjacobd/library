import argparse, sys

from xklb import usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library cluster-sort", usage=usage.cluster_sort)
    parser.add_argument("--model", "-m", help="Use a specific spaCy model")
    parser.add_argument("--clusters", "--n-clusters", "-c", type=int, help="Number of KMeans clusters")
    parser.add_argument("--groups", "-g", action="store_true", help="Show groups")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("input_path", nargs="?", type=argparse.FileType("r"), default=sys.stdin)
    parser.add_argument("output_path", nargs="?")
    args = parser.parse_args()

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def cluster_sort() -> None:
    args = parse_args()

    lines = args.input_path.readlines()
    args.input_path.close()

    groups = utils.cluster_paths(lines, args.model, args.clusters)
    groups = sorted(groups, key=lambda d: (len(d["grouped_paths"]), -len(d["common_prefix"])))

    if args.groups:
        from rich import print

        print(groups)
    else:
        lines = utils.flatten(d["grouped_paths"] for d in groups)
        if args.output_path:
            with open(args.output_path, "w") as output_fd:
                output_fd.writelines(lines)
        else:
            sys.stdout.writelines(lines)


if __name__ == "__main__":
    cluster_sort()
