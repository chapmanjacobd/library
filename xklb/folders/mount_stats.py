from xklb import usage
from xklb.utils import arggroups, argparse_utils
from xklb.utils.devices import get_mount_stats

# TODO: filter out mount points with different paths but are subpaths of the same mount point


def mount_stats() -> None:
    parser = argparse_utils.ArgumentParser(usage=usage.mount_stats)
    arggroups.debug(parser)

    parser.add_argument("mounts", nargs="+")
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    space = get_mount_stats(args.mounts)

    print("Relative disk dependence:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['used'] * 80)} {d['used']:.1%}")

    print("\nRelative free space:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['free'] * 80)} {d['free']:.1%}")
