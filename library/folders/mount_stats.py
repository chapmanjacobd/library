import shutil

from library.utils import arggroups, argparse_utils, devices, strings
from library.utils.devices import get_mount_stats

USAGE = {
    'disk_free': r"""library filesystem free mounts [MOUNTPOINT ...]

    Print total disk usage and disk free stats

        library filesystem free mounts
""",
    'mount_stats': r"""library filesystem stats mounts MOUNTPOINT ...

    Print relative use and free for multiple mount points

        lb filesystem mounts stats (fd -td -d1 'd[0-9]+$' /mnt)
        Relative disk dependence:
        /mnt/d1: ###### 8.1%
        /mnt/d2: ######### 12.2%
        /mnt/d3: ######### 12.2%
        /mnt/d4: ####### 9.5%
        /mnt/d5: ####### 9.5%
        /mnt/d6: ######### 12.2%
        /mnt/d7: ######### 12.2%
        /mnt/d8: ######### 12.2%
        /mnt/d9: ######### 12.2%

        Relative free space:
        /mnt/d1: ##### 6.9%
        /mnt/d2: ########### 13.8%
        /mnt/d3: ######## 10.4%
        /mnt/d4: ######## 10.5%
        /mnt/d5: ###### 8.7%
        /mnt/d6: ######### 11.8%
        /mnt/d7: ######### 11.9%
        /mnt/d8: ######### 12.2%
        /mnt/d9: ########### 13.8%
""",
}


def disk_free() -> None:
    parser = argparse_utils.ArgumentParser(usage=USAGE['disk_free'])
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
    parser = argparse_utils.ArgumentParser(usage=USAGE['mount_stats'])
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
