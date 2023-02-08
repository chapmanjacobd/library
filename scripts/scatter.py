import argparse, random, tempfile
from pathlib import Path
from statistics import median
from typing import List

from humanize import naturalsize
from tabulate import tabulate

from xklb import consts, db, utils
from xklb.utils import log

scatter_usage = """library scatter [--limit LIMIT] [--policy POLICY] [--sort SORT] --srcmounts SRCMOUNTS database relative_paths ...

    Balance size

        $ library scatter -m /mnt/d1:/mnt/d2:/mnt/d3:/mnt/d4/:/mnt/d5:/mnt/d6:/mnt/d7 ~/lb/fs/scatter.db subfolder/of/mergerfs/mnt
        Current path distribution:
        ╒═════════╤══════════════╤══════════════╤═══════════════╤════════════════╤═════════════════╤════════════════╕
        │ mount   │   file_count │ total_size   │ median_size   │ time_created   │ time_modified   │ time_scanned   │
        ╞═════════╪══════════════╪══════════════╪═══════════════╪════════════════╪═════════════════╪════════════════╡
        │ /mnt/d1 │        12793 │ 169.5 GB     │ 4.5 MB        │ Jan 27         │ Jul 19 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d2 │        13226 │ 177.9 GB     │ 4.7 MB        │ Jan 27         │ Jul 19 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d3 │            1 │ 717.6 kB     │ 717.6 kB      │ Jan 31         │ Jul 18 2022     │ yesterday      │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d4 │           82 │ 1.5 GB       │ 12.5 MB       │ Jan 31         │ Apr 22 2022     │ yesterday      │
        ╘═════════╧══════════════╧══════════════╧═══════════════╧════════════════╧═════════════════╧════════════════╛

        Simulated path distribution:
        5845 files should be moved
        20257 files should not be moved
        ╒═════════╤══════════════╤══════════════╤═══════════════╤════════════════╤═════════════════╤════════════════╕
        │ mount   │   file_count │ total_size   │ median_size   │ time_created   │ time_modified   │ time_scanned   │
        ╞═════════╪══════════════╪══════════════╪═══════════════╪════════════════╪═════════════════╪════════════════╡
        │ /mnt/d1 │         9989 │ 46.0 GB      │ 2.4 MB        │ Jan 27         │ Jul 19 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d2 │        10185 │ 46.0 GB      │ 2.4 MB        │ Jan 27         │ Jul 19 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d3 │         1186 │ 53.6 GB      │ 30.8 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d4 │         1216 │ 49.5 GB      │ 29.5 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d5 │         1146 │ 53.0 GB      │ 30.9 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d6 │         1198 │ 48.8 GB      │ 30.6 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d7 │         1182 │ 52.0 GB      │ 30.9 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ╘═════════╧══════════════╧══════════════╧═══════════════╧════════════════╧═════════════════╧════════════════╛
        ### Move 1182 files to /mnt/d7 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmpmr1628ij / /mnt/d7
        ### Move 1198 files to /mnt/d6 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmp9yd75f6j / /mnt/d6
        ### Move 1146 files to /mnt/d5 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmpfrj141jj / /mnt/d5
        ### Move 1185 files to /mnt/d3 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmpqh2euc8n / /mnt/d3
        ### Move 1134 files to /mnt/d4 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmphzb0gj92 / /mnt/d4

    Balance device inodes for specific subfolder

        $ library scatter -m /mnt/d1:/mnt/d2 ~/lb/fs/scatter.db subfolder --group count --sort 'size desc'

    Scatter the most recent 100 files

        $ library scatter -m /mnt/d1:/mnt/d2 -l 100 -s 'time_modified desc' ~/lb/fs/scatter.db /

    Scatter without mountpoints (limited functionality; only good for balancing fs inodes)

        $ library scatter scatter.db /test/{0,1,2,3,4,5,6,7,8,9}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(usage=scatter_usage)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue")
    parser.add_argument("--policy", "-p")
    parser.add_argument("--group", "-g")
    parser.add_argument("--sort", "-s", default="random()", help="Sort files before moving")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--srcmounts", "-m", help="/mnt/d1:/mnt/d2")

    parser.add_argument("database")
    parser.add_argument(
        "relative_paths",
        nargs="+",
        help="Paths to scatter, relative to the root of your mergerfs mount if using -m, any path substring is valid",
    )
    args = parser.parse_args()
    args.db = db.connect(args)

    if args.srcmounts:
        args.srcmounts = [m.rstrip("\\/") for m in args.srcmounts.split(":")]
        if args.group is None:
            args.group = "size"
        if args.policy is None:
            args.policy = "pfrd"
    else:
        if args.group is None:
            args.group = "count"
        if args.policy is None:
            args.policy = "rand"

    args.relative_paths = [p.lstrip(".") for p in args.relative_paths]

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def get_table(args) -> List[dict]:
    or_paths = [f"path like :path_{i}" for i, _path in enumerate(args.relative_paths)]

    media = list(
        args.db.query(
            f"""
        select
            path
            , size
            , time_created
            , time_modified
            , time_downloaded
        from media
        where 1=1
            and time_deleted = 0
            and is_dir is NULL
            and ({' or '.join(or_paths)})
        order by {args.sort}
        {'limit :limit' if args.limit else ''}
        """,
            {
                "limit": args.limit,
                **{f"path_{i}": f"%{path}%" for i, path in enumerate(args.relative_paths) if args.relative_paths},
            },
        )
    )

    return media


def get_path_stats(args, data):
    result = []
    for srcmount in args.srcmounts:
        disk_files = [d for d in data if d["path"].startswith(srcmount)]
        if disk_files:
            result.append(
                {
                    "mount": srcmount,
                    "file_count": len(disk_files),
                    "total_size": sum(d["size"] for d in disk_files),
                    "median_size": median(d["size"] for d in disk_files),
                    "time_created": median(d["time_created"] for d in disk_files),
                    "time_modified": median(d["time_modified"] for d in disk_files),
                    "time_scanned": median(d["time_downloaded"] for d in disk_files),
                },
            )
    return result


def print_path_stats(tbl):
    tbl = utils.list_dict_filter_bool(tbl, keep_0=False)
    tbl = utils.col_naturalsize(tbl, "total_size")
    tbl = utils.col_naturalsize(tbl, "median_size")
    for t in consts.TIME_COLUMNS:
        utils.col_naturaldate(tbl, t)

    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))


def rebin_files(args, disk_stats, all_files):
    total_size = sum(d["size"] for d in all_files)

    untouched = []
    to_rebin = []
    full_disks = []
    for disk_stat in disk_stats:
        disk_files = [d for d in all_files if d["path"].startswith(disk_stat["mount"])]

        disk_rebin = []
        if disk_files:
            if args.group == "size":
                ideal_allocation_size = total_size * disk_stat["total"]

                size = 0
                for file in disk_files:
                    size += file["size"]
                    if size < ideal_allocation_size:
                        untouched.append(file)
                    else:
                        disk_rebin.append({"mount": disk_stat["mount"], **file})
            else:
                ideal_allocation_count = len(disk_files) // len(disk_stats)
                untouched.extend(disk_files[:ideal_allocation_count])
                disk_rebin.extend({"mount": disk_stat["mount"], **file} for file in disk_files[ideal_allocation_count:])

        if len(disk_rebin) > 0:
            full_disks.append(disk_stat["mount"])
        to_rebin.extend(disk_rebin)

    if len(disk_stats) == len(full_disks):
        log.warning(
            "No valid targets. You have selected an ideal state which is significantly different from the current path distribution."
        )
        log.warning(
            'For this run, "full" source disks will be treated as valid targets. Otherwise, there is nothing to do.'
        )
        full_disks = []

    rebinned = []
    for file in to_rebin:
        valid_targets = [d for d in disk_stats if d["mount"] not in [*full_disks, file["mount"]]]

        mount_list = [d["mount"] for d in valid_targets]
        if args.policy in ["free", "pfrd"]:
            new_mount = random.choices(mount_list, weights=[stat["free"] for stat in valid_targets], k=1)[0]
        elif args.policy in ["used", "purd"]:
            new_mount = random.choices(mount_list, weights=[stat["used"] for stat in valid_targets], k=1)[0]
        elif args.policy in ["total", "ptrd"]:
            new_mount = random.choices(mount_list, weights=[stat["total"] for stat in valid_targets], k=1)[0]
        else:
            new_mount = random.choices(mount_list, k=1)[0]

        file["from_path"] = file["path"]
        file["path"] = file["path"].replace(file["mount"], new_mount)
        rebinned.append(file)

    return untouched, rebinned


def get_rel_stats(parents, files):
    mount_space = []
    total_used = 1
    for parent in parents:
        used = sum([file["size"] for file in files if file["path"].startswith(parent)])
        total_used += used
        mount_space.append([parent, used])

    return [
        {"mount": mount, "used": used / total_used, "free": used / total_used, "total": used / total_used}
        for mount, used in mount_space
    ]


def scatter() -> None:
    args = parse_args()

    files = get_table(args)

    if args.srcmounts:
        disk_stats = utils.get_mount_stats(args.srcmounts)
    else:
        log.warning(
            "srcmounts was not provided (-m) so provided paths will only be compared with each other. This might not be what you want!!"
        )
        log.warning("In this setting paths should be absolute!--and the only valid policies are: `rand`, `used`.")
        args.srcmounts = [str(Path(p).resolve()) for p in args.relative_paths]
        disk_stats = get_rel_stats(args.srcmounts, files)

    if len(disk_stats) < 2:
        log.error(
            (
                "\nThis tool does not make sense to use for only one path."
                " Define more paths or use the -m flag to define mountpoints which share the same subfolder (eg. mergerfs)"
            )
        )
        raise SystemExit(2)

    path_stats = get_path_stats(args, files)
    print("\nCurrent path distribution:")
    print_path_stats(path_stats)

    untouched, rebinned = rebin_files(args, disk_stats, files)

    print("\nSimulated path distribution:")
    path_stats = get_path_stats(args, rebinned + untouched)
    print_path_stats(path_stats)
    print(len(rebinned), "files would be moved", "(" + naturalsize(sum(d["size"] for d in rebinned)) + ")")
    print(len(untouched), "files would not be moved", "(" + naturalsize(sum(d["size"] for d in untouched)) + ")")

    print("\n######### Commands to run #########")
    for disk_stat in sorted(disk_stats, key=lambda d: d["free"], reverse=True):
        dest_disk_files = [
            d["from_path"].replace(d["mount"], d["mount"] + "/.")
            for d in rebinned
            if d["path"].startswith(disk_stat["mount"])
        ]

        if len(dest_disk_files) == 0:
            continue

        temp_file = Path(tempfile.mktemp())
        with temp_file.open("w") as f:
            f.writelines("\n".join(dest_disk_files))

        print(
            f"""### Move {len(dest_disk_files)} files to {disk_stat['mount']}: ###
rsync -aE --xattrs --info=progress2 --remove-source-files --files-from={temp_file} / {disk_stat['mount']}"""
        )


if __name__ == "__main__":
    scatter()
