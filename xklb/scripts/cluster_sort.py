import argparse, sys
from pathlib import Path
from pprint import pprint

from xklb import consts, usage, utils
from xklb.consts import DBType
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library cluster-sort", usage=usage.cluster_sort)

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--lines",
        action="store_const",
        dest="profile",
        const="lines",
        help="Cluster lines AS-IS",
    )
    profile.add_argument(
        "--image",
        "-I",
        action="store_const",
        dest="profile",
        const=DBType.image,
        help="Read image data",
    )
    profile.add_argument(
        "--audio",
        "-A",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Read audio data",
    )
    profile.add_argument(
        "--video",
        "-V",
        action="store_const",
        dest="profile",
        const=DBType.video,
        help="Read video data",
    )
    profile.add_argument(
        "--text",
        "-T",
        action="store_const",
        dest="profile",
        const=DBType.text,
        help="Read text data",
    )
    parser.set_defaults(profile="lines")

    parser.add_argument("--clusters", "--n-clusters", "-c", type=int, help="Number of KMeans clusters")
    parser.add_argument("--print-groups", "--groups", "-g", action="store_true", help="Print groups")
    parser.add_argument("--move-groups", "-M", action="store_true", help="Move groups into subfolders")
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

    if args.profile == "lines":
        groups = utils.cluster_paths(lines, args.clusters)
    elif args.profile == "image":
        groups = utils.cluster_images(lines, args.clusters)
    else:
        raise NotImplementedError
    groups = sorted(groups, key=lambda d: (len(d["grouped_paths"]), -len(d["common_prefix"])))

    if args.print_groups:
        for group in groups:
            group["grouped_paths"] = [s.rstrip("\n") for s in group["grouped_paths"]]

        pprint(groups)
    elif args.move_groups:
        min_len = len(str(len(groups) + 1))

        if args.profile == "lines":
            if args.output_path:
                output_parent = Path(args.output_path).parent
                output_name = Path(args.output_path).name
            elif args.input_path.name == "<stdin>" or Path(args.input_path.name).parent == consts.TEMP_DIR:
                output_parent = Path.cwd()
                output_name = "stdin"
            else:
                output_parent = Path(args.input_path.name).parent
                output_name = Path(args.input_path.name).name

            for i, group in enumerate(groups, start=1):
                output_path = output_parent / (output_name + "_" + str(i).zfill(min_len))
                with open(output_path, "w") as output_fd:
                    output_fd.writelines(group["grouped_paths"])

        elif args.profile in ("image",):
            for i, group in enumerate(groups, start=1):
                paths = [s.rstrip("\n") for s in group["grouped_paths"]]
                utils.move_files([(p, str(Path(p).parent / str(i).zfill(min_len) / Path(p).name)) for p in paths])
    else:
        lines = utils.flatten(d["grouped_paths"] for d in groups)
        if args.output_path:
            with open(args.output_path, "w") as output_fd:
                output_fd.writelines(lines)
        else:
            utils.pipe_lines(lines)


if __name__ == "__main__":
    cluster_sort()
