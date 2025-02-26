import shutil

from library import usage
from library.utils import arggroups, argparse_utils, devices, strings
from library.utils.devices import get_mount_stats


def disk_free() -> None:
    parser = argparse_utils.ArgumentParser(usage=usage.disk_free)
    arggroups.debug(parser)

    parser.add_argument("mounts", nargs="*", action=argparse_utils.ArgparseArgsOrStdin)
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    if not args.mounts:
        args.mounts = devices.mountpoints()

    total_total = 0
    total_used = 0
    total_free = 0
    for src_mount in args.mounts:
        total, used, free = shutil.disk_usage(src_mount)
        total_total += total
        total_used += used
        total_free += free

    print(
        f"total={strings.file_size(total_total)} used={strings.file_size(total_used)} free={strings.file_size(total_free)}"
    )


def mount_stats() -> None:
    parser = argparse_utils.ArgumentParser(usage=usage.mount_stats)
    arggroups.debug(parser)

    parser.add_argument("mounts", nargs="*", action=argparse_utils.ArgparseArgsOrStdin)
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    if not args.mounts:
        args.mounts = devices.mountpoints()

    space = get_mount_stats(args.mounts)

    print("Relative disk dependence:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['used'] * 80)} {d['used']:.1%}")
    print()

    print("Relative free space:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['free'] * 80)} {d['free']:.1%}")
