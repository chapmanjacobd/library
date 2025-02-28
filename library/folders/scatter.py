import argparse, math, operator, os, random, shutil, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path

from library import usage
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    devices,
    file_utils,
    iterables,
    nums,
    printing,
    strings,
)
from library.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.scatter)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue")
    parser.add_argument("--max-files-per-folder", "--max-files-per-directory", type=int)
    parser.add_argument("--policy")
    parser.add_argument("--group")
    parser.add_argument("--sort", default="random()", help="Sort files before moving")
    parser.add_argument("--targets", "--srcmounts", "-m", help="Colon separated destinations eg. /mnt/d1:/mnt/d2")
    parser.add_argument(
        "--consolidate", action="store_true", help="Group files by folder--similar to mergerfs existing-path policies"
    )
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument(
        "relative_paths",
        nargs="*",
        help="Paths to scatter; if using -m any path substring is valid (relative to the root of your mergerfs mount)",
    )
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    if args.targets:
        args.targets = [m.rstrip("\\/") for m in args.targets.split(":")]
        if args.group is None:
            args.group = "size"
        if args.policy is None:
            args.policy = "pfrd"
    else:
        if args.group is None:
            args.group = "count"
        if args.policy is None:
            args.policy = "rand"

    if args.targets and args.max_files_per_folder:
        msg = (
            "--max-files-per-folder has no affect during multi-device re-bin operation. Run as an independent operation"
        )
        raise ValueError(msg)

    if args.targets is None and args.policy not in ("rand", "used"):
        msg = "Without targets defined the only meaningful policies are: `rand` or `used`"
        raise ValueError(msg)

    args.relative_paths = file_utils.resolve_absolute_paths(args.relative_paths)
    args.targets = file_utils.resolve_absolute_paths(args.targets)

    return args


def get_table(args) -> list[dict]:
    m_columns = db_utils.columns(args, "media")
    or_paths = [f"path like :path_{i}" for i, _path in enumerate(args.relative_paths)]
    or_paths_sql = f"and ({' or '.join(or_paths)})"

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
            and coalesce(time_deleted, 0)=0
            and path not like "http%"
            {'and coalesce(is_dir, 0)=0' if 'is_dir' in m_columns else ""}
            {or_paths_sql if args.relative_paths else ''}
        order by {args.sort}
        {'limit :limit' if args.limit else ''}
        """,
            {
                "limit": args.limit,
                **{
                    f"path_{i}": f"{path}%" if path.startswith(os.sep) else f"%{path}%"
                    for i, path in enumerate(args.relative_paths)
                    if args.relative_paths
                },
            },
        ),
    )

    return media


def get_path_stats(args, data) -> list[dict]:
    read_only_mounts = [
        s for s in args.relative_paths if Path(s).is_absolute() and not any(m in s for m in args.targets)
    ]
    if read_only_mounts:
        log.info("Treating as depletion targets: %s", read_only_mounts)

    result = []
    for srcmount in args.targets + read_only_mounts:
        disk_files = [d for d in data if d["path"].startswith(srcmount)]
        if disk_files:
            result.append(
                {
                    "mount": srcmount,
                    "file_count": len(disk_files),
                    "total_size": sum(d["size"] or 0 for d in disk_files),
                    "median_size": nums.safe_median(d["size"] or 0 for d in disk_files),
                    "time_created": nums.safe_median(d["time_created"] for d in disk_files),
                    "time_modified": nums.safe_median(d["time_modified"] for d in disk_files),
                    "time_downloaded": nums.safe_median(d["time_downloaded"] for d in disk_files),
                },
            )
    return result


def print_path_stats(tbl) -> None:
    tbl = iterables.list_dict_filter_bool(tbl, keep_0=False)
    tbl = printing.col_filesize(tbl, "total_size")
    tbl = printing.col_filesize(tbl, "median_size")
    for t in consts.EPOCH_COLUMNS:
        printing.col_naturaldate(tbl, t)

    printing.table(tbl)


def rebin_files(args, disk_stats, all_files) -> tuple[list, list]:
    total_size = sum(d["size"] or 0 for d in all_files)

    untouched = []
    to_rebin = []
    full_disks = []

    read_only_mounts = [
        s for s in args.relative_paths if Path(s).is_absolute() and not any(m in s for m in args.targets)
    ]
    for disk_stat in devices.get_mount_stats(read_only_mounts):
        disk_files = [d for d in all_files if d["path"].startswith(disk_stat["mount"])]
        to_rebin.extend({"mount": disk_stat["mount"], **file} for file in disk_files)

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
            "No valid targets. You have selected an ideal state which is too similar or too different from the current path distribution.",
        )
        log.warning(
            'For this run, "full" source disks will be treated as valid targets. Otherwise, there is nothing to do.',
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


def get_rel_stats(parents, files) -> list[dict[str, float | str]]:
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


def rebin_folders(paths, max_files_per_folder=16000):
    parent_counts = Counter(Path(p).parent for p in paths)
    rebinned_tuples = []
    untouched = []
    parent_index = {}
    parent_current_count = {}

    for p in paths:
        path = Path(p)
        parent = path.parent
        if parent_counts[parent] > max_files_per_folder:
            if parent not in parent_index:
                parent_index[parent] = 1
                parent_current_count[parent] = 0

            min_len = math.floor(parent_counts[parent] / max_files_per_folder)
            rebinned_tuples.append((p, str(parent / str(parent_index[parent]).zfill(len(str(min_len))) / path.name)))
            parent_current_count[parent] += 1

            _quotient, remainder = divmod(parent_current_count[parent], max_files_per_folder)
            if remainder == 0:
                parent_index[parent] += 1
        else:
            untouched.append(p)

    return untouched, rebinned_tuples


def rebin_consolidate(args, _disk_stats, all_files) -> tuple[list, list]:
    total_size = sum(d["size"] or 0 for d in all_files)
    print(strings.file_size(total_size), len(all_files), "files total")

    disk_free = {
        src_mount: shutil.disk_usage(src_mount).free for src_mount in sorted(args.targets, key=len, reverse=True)
    }

    folder_files = defaultdict(list)
    for file_dict in sorted(all_files, key=operator.itemgetter("size")):
        for mount_point in disk_free.keys():
            if file_dict["path"].startswith(mount_point + os.sep):
                file_dict["mount"] = mount_point

                relative_path = file_dict["path"].replace(mount_point, "", 1).lstrip(os.sep)
                folder_path = os.path.dirname(relative_path)
                folder_files[folder_path].append(file_dict)
                break
        if not "mount" in file_dict:
            log.debug("No mountpoint found %s", file_dict["path"])

    # log.debug('folder_files %s', folder_files)

    untouched = []
    rebinned = []
    for folder_path, files_in_folder in folder_files.items():
        folder_weights = []
        for mount_point in disk_free.keys():
            folder_file_count = 0
            folder_file_size = 0
            for file_dict in files_in_folder:
                if file_dict["mount"] == mount_point:
                    folder_file_count += 1
                    folder_file_size += file_dict.get("size", 0) or 0
            if folder_file_count:
                folder_weights.append(
                    {
                        "mount_point": mount_point,
                        "folder_weight": (folder_file_count / 20) + (folder_file_size / (1024 * 1024)),
                    }
                )

        folder_weights = sorted(folder_weights, key=operator.itemgetter("folder_weight"), reverse=True)
        if len(folder_weights) <= 1:  # no need to move any files
            untouched.extend(files_in_folder)
            continue

        # log.info("Binning %s", folder_path)
        # log.debug(folder_weights)

        target_mount = None
        total_folder_size = sum(d["size"] for d in files_in_folder)
        for d in folder_weights:
            mount_point = d["mount_point"]
            if disk_free[mount_point] >= total_folder_size:
                target_mount = mount_point
                break

        if not target_mount:
            most_free = max(disk_free.values())
            mount_point = [k for k, v in disk_free.items() if v == most_free][0]
            if disk_free[mount_point] >= total_folder_size:
                target_mount = mount_point

        if not target_mount:
            log.warning("Could not determine target mount %s (not enough planned free space)", folder_path)
            untouched.extend(files_in_folder)
            continue

        for file_dict in files_in_folder:
            current_mount = file_dict["mount"]

            if current_mount == target_mount:
                untouched.append(file_dict)
            else:
                # Move file to target mount (virtually)
                disk_free[current_mount] += file_dict["size"]
                disk_free[target_mount] -= file_dict["size"]

                file_dict["mount"] = current_mount
                file_dict["from_path"] = file_dict["path"]
                relative_file_path = file_dict["path"].replace(current_mount, "", 1)
                file_dict["path"] = os.path.join(target_mount, relative_file_path.lstrip(os.sep))

                rebinned.append(file_dict)

    return untouched, rebinned


def scatter() -> None:
    args = parse_args()

    files = get_table(args)

    if args.max_files_per_folder:
        paths = [d["path"] for d in files]
        untouched, rebinned = rebin_folders(paths, args.max_files_per_folder)

        tbl = []
        for existing_path, new_path in rebinned:
            tbl.append({"existing_path": existing_path, "new_path": new_path})
            if len(tbl) > 10:
                break
        tbl = printing.col_resize_percent(tbl, "existing_path", width=20)
        tbl = printing.col_resize_percent(tbl, "new_path", width=20)
        printing.table(tbl)
        print(len(rebinned), "files would be moved (only 10 shown)")
        print(len(untouched), "files would not be moved")
        file_utils.move_files_bash(rebinned)
        sys.exit(0)

    if args.targets:
        disk_stats = devices.get_mount_stats(args.targets)
    else:
        log.warning(
            "targets were not provided (-m) so provided paths will only be compared with each other. This might not be what you want!!",
        )
        args.targets = args.relative_paths
        disk_stats = get_rel_stats(args.targets, files)

    if len(disk_stats) < 2:
        log.error(
            "\nThis tool does not make sense to use for only one path."
            " Define more paths or use the -m flag to define mountpoints which share the same subfolder (eg. mergerfs)",
        )
        raise SystemExit(2)

    path_stats = get_path_stats(args, files)
    print("\nCurrent path distribution:")
    print_path_stats(path_stats)

    if args.consolidate:
        untouched, rebinned = rebin_consolidate(args, disk_stats, files)
    else:
        untouched, rebinned = rebin_files(args, disk_stats, files)

    print("\nSimulated path distribution:")
    path_stats = get_path_stats(args, rebinned + untouched)
    print_path_stats(path_stats)
    print(len(rebinned), "files would be moved", "(" + strings.file_size(sum(d["size"] or 0 for d in rebinned)) + ")")
    print(
        len(untouched),
        "files would not be moved",
        "(" + strings.file_size(sum(d["size"] or 0 for d in untouched)) + ")",
    )

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
rsync -aE --xattrs --info=progress2 --remove-source-files --files-from={temp_file} / {disk_stat['mount']}""",
        )
