import argparse, random, shutil, tempfile
from pathlib import Path
from statistics import median
from typing import List

from tabulate import tabulate

from xklb import consts, db, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        usage="""library scatter [--limit LIMIT] [--policy POLICY] [--sort SORT] --srcmounts SRCMOUNTS database relative_paths ...

    Balance your disks

        $ library scatter -m /mnt/d1:/mnt/d2:/mnt/d3:/mnt/d4/:/mnt/d5:/mnt/d6:/mnt/d7 ~/lb/fs/scatter.db --sort size subfolder/of/mergerfs/mnt
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

    Scatter the most recent 100 files

        $ library scatter -m /mnt/d1:/mnt/d2:/mnt/d3:/mnt/d4/:/mnt/d5:/mnt/d6:/mnt/d7 -l 100 -s 'time_modified desc' ~/lb/fs/scatter.db /

    Show disk usage (why not?)

        $ library scatter -m /mnt/d1:/mnt/d2:/mnt/d3:/mnt/d4/:/mnt/d5:/mnt/d6:/mnt/d7 ~/lb/fs/scatter.db / --usage
        Relative disk utilization:
            /mnt/d1: ################# 22.2 percent
            /mnt/d2: ################# 22.2 percent
            /mnt/d3: #### 5.5 percent
            /mnt/d4: ########################## 33.4 percent
            /mnt/d5: ############# 16.6 percent
            /mnt/d6:  0.0 percent
            /mnt/d7:  0.0 percent
        Relative free space:
            /mnt/d1:  0.1 percent
            /mnt/d2:  0.1 percent
            /mnt/d3:  0.1 percent
            /mnt/d4:  0.1 percent
            /mnt/d5: ########## 13.6 percent
            /mnt/d6: ############################## 37.6 percent
            /mnt/d7: ###################################### 48.4 percent

    """
    )
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue")
    parser.add_argument("--policy", "-p", default="pfrd")
    parser.add_argument("--group", "-g", default="size")
    parser.add_argument("--sort", "-s", default="random()", help="Sort files before moving")
    parser.add_argument("--usage", "-u", action="store_true", help="Show disk usage")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--srcmounts", "-m", required=True, help="/mnt/d1:/mnt/d2")

    parser.add_argument("database")
    parser.add_argument(
        "relative_paths",
        nargs="+",
        help="Paths to scatter, relative to the root of your mergerfs mount; any path substring is valid",
    )
    args = parser.parse_args()
    args.db = db.connect(args)

    args.srcmounts = [m.rstrip("\\/") for m in args.srcmounts.split(":")]
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


def get_disk_stats(src_mounts):
    mount_space = []
    total_used = 0
    total_free = 0
    grand_total = 0
    for src_mount in src_mounts:
        total, used, free = shutil.disk_usage(src_mount)
        total_used += used
        total_free += free
        grand_total += total
        mount_space.append((src_mount, used, free, total))

    return [
        {"mount": mount, "used": used / total_used, "free": free / total_free, "total": total / grand_total}
        for mount, used, free, total in mount_space
    ]


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


def print_disk_stats(space):
    print("Relative disk utilization:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['used'] * 80)} {d['used']:.1%}")

    print("\nRelative free space:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['free'] * 80)} {d['free']:.1%}")


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


def scatter() -> None:
    args = parse_args()

    disk_stats = get_disk_stats(args.srcmounts)
    if args.usage:
        print_disk_stats(disk_stats)
        raise SystemExit(0)

    files = get_table(args)

    path_stats = get_path_stats(args, files)
    print("\nCurrent path distribution:")
    print_path_stats(path_stats)

    untouched, rebinned = rebin_files(args, disk_stats, files)

    print("\nSimulated path distribution:")
    print(len(rebinned), "files should be moved")
    print(len(untouched), "files should not be moved")
    path_stats = get_path_stats(args, rebinned + untouched)
    print_path_stats(path_stats)

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
