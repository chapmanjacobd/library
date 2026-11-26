import argparse
from collections import defaultdict

from library import usage
from library.filesystem.disk_usage import check_depth, count_folders, format_folder, split_path
from library.play import media_printer
from library.table import mcda
from library.utils import (
    arggroups,
    argparse_utils,
    file_utils,
    filter_engine,
    iterables,
    nums,
    shell_utils,
    sqlgroups,
)

MIN_PATH_PARTS = 2
MIN_CLUSTER_MEDIA = 2


def _aggregate_media(grouped_media) -> dict:
    alive_media = [m for m in grouped_media if not bool(m.get("time_deleted"))]
    deleted_media = [m for m in grouped_media if bool(m.get("time_deleted"))]
    return {
        "size": sum(m.get("size") or 0 for m in alive_media),
        "median_size": nums.safe_median(m.get("size") for m in alive_media),
        "duration": sum(m.get("duration") or 0 for m in alive_media),
        "median_duration": nums.safe_median(m.get("duration") for m in alive_media),
        "total": len(grouped_media),
        "exists": len(alive_media),
        "deleted": len(deleted_media),
        "deleted_size": sum(m.get("size") or 0 for m in deleted_media),
        "deleted_duration": sum(m.get("duration") or 0 for m in deleted_media),
        "played": sum(bool(m.get("time_last_played")) for m in grouped_media),
    }


def _weighted_median(values_and_weights) -> float | None:
    # Approximate a median from per-folder medians without the original file list.
    values_and_weights = sorted(
        (value, weight) for value, weight in values_and_weights if value is not None and weight > 0
    )
    total = sum(weight for _, weight in values_and_weights)
    if total == 0:
        return None

    def value_at(position):
        cumulative = 0
        for value, weight in values_and_weights:
            cumulative += weight
            if position <= cumulative:
                return value
        return values_and_weights[-1][0]

    if total & 1:
        return value_at((total + 1) // 2)
    return (value_at(total // 2) + value_at(total // 2 + 1)) / 2


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.big_dirs)
    arggroups.sql_fs(parser)
    arggroups.files(parser)

    arggroups.text_filtering(parser)
    arggroups.cluster_sort(parser)
    arggroups.group_folders(parser)
    arggroups.debug(parser)

    arggroups.database_optional(parser)
    arggroups.paths_or_stdin(parser, required=False)
    args = parser.parse_intermixed_args()
    arggroups.database_paths_post(args)
    arggroups.args_post(args, parser)

    arggroups.files_post(args)
    arggroups.sql_fs_post(args)
    arggroups.group_folders_post(args)

    return args


def _is_url_path(path) -> bool:
    return "://" in str(path)


def group_files_by_parents(media) -> list[dict]:
    # Folder grouping is for local files; URLs are not filesystem folders.
    media = [m for m in media if not _is_url_path(m["path"])]
    split_media = [(split_path(m["path"]), m) for m in media]
    min_parts = min((len(parts) for (parts, _), _ in split_media), default=10)

    p_media = {}
    for (parts, sep), m in split_media:
        p = list(parts)
        while len(p) >= MIN_PATH_PARTS:
            p.pop()
            parent = sep.join(p) or sep

            if parent not in p_media:
                p_media[parent] = [m]
            else:
                p_media[parent].append(m)

    d = {}
    for parent, grouped_media in list(p_media.items()):
        d[parent] = _aggregate_media(grouped_media)

    # Keep the parent folder of the shallowest file and every deeper folder.
    min_parent_parts = min_parts - 1
    for parent, _ in list(d.items()):
        parts, _ = split_path(parent)
        if len(parts) < min_parent_parts:
            d.pop(parent)

    parents = set(d.keys())
    subdirectory_count = count_folders(parents)
    for parent, data in d.items():
        data["folders"] = subdirectory_count[parent]

    return [{**v, "path": format_folder(k)} for k, v in d.items()]


def group_files_by_parent(media) -> list[dict]:
    p_media = defaultdict(list)
    for m in media:
        if not _is_url_path(m["path"]):
            parts, sep = split_path(m["path"])
            p_media[sep.join(parts[:-1]) or "."].append(m)

    d = {}
    for parent, grouped_media in list(p_media.items()):
        d[parent] = {**_aggregate_media(grouped_media), "folders": 0}

    return [{"path": format_folder(k), **v} for k, v in d.items()]


def group_media_by_depth(media, args) -> list[dict]:
    # Group media directly at the requested depth so each file is counted once.
    groups = defaultdict(list)
    child_dirs = defaultdict(set)
    for m in media:
        if _is_url_path(m["path"]):
            continue

        parts, sep = split_path(m["path"])
        if len(parts) < MIN_PATH_PARTS:
            continue

        folder_parts = parts[:-1]
        if args.max_depth:
            folder_parts = folder_parts[: args.max_depth]
        if not folder_parts or not check_depth(args, len(folder_parts)):
            continue

        parent = sep.join(folder_parts) or sep
        groups[parent].append(m)

        if len(parts) - 1 > len(folder_parts):
            child = parts[len(folder_parts)]
            if child:
                child_dirs[parent].add(child)

    return [
        {
            "path": format_folder(parent),
            **_aggregate_media(grouped_media),
            "folders": len(child_dirs[parent]),
        }
        for parent, grouped_media in groups.items()
    ]


def reaggregate_at_depth(args, folders, media=None) -> list[dict]:
    if media is not None:
        return group_media_by_depth(media, args)

    # Fallback for callers that only have aggregated folder rows (eg. cluster_sort).
    # Prefer passing media so sums and medians can be recomputed exactly.
    d = {}
    child_dirs = defaultdict(set)
    for f in folders:
        original_parts, sep = split_path(f["path"])
        p = original_parts
        if args.max_depth:
            p = p[: args.max_depth]
        if not check_depth(args, len(p)):
            continue

        parent = sep.join(p) or sep
        if len(original_parts) > len(p):
            child = original_parts[len(p)]
            if child:
                child_dirs[parent].add(child)

        if d.get(parent):
            prev_exists = d[parent]["exists"]
            d[parent]["median_size"] = _weighted_median([
                (d[parent].get("median_size"), prev_exists),
                (f.get("median_size"), f.get("exists") or 0),
            ])
            d[parent]["median_duration"] = _weighted_median([
                (d[parent].get("median_duration"), prev_exists),
                (f.get("median_duration"), f.get("exists") or 0),
            ])
            d[parent]["size"] += f["size"]
            d[parent]["duration"] += f["duration"]
            d[parent]["total"] += f["total"]
            d[parent]["exists"] += f["exists"]
            d[parent]["deleted"] += f["deleted"]
            d[parent]["deleted_size"] = (d[parent].get("deleted_size") or 0) + (f.get("deleted_size") or 0)
            d[parent]["deleted_duration"] = (d[parent].get("deleted_duration") or 0) + (f.get("deleted_duration") or 0)
            d[parent]["played"] += f["played"]
        else:
            d[parent] = {"folders": 0, **f}

    for parent, data in d.items():
        if parent in child_dirs:
            data["folders"] = len(child_dirs[parent])

    return [{**v, "path": format_folder(k)} for k, v in d.items()]


def process_big_dirs(args, folders, media=None) -> list[dict]:
    if args.depth and media is not None:
        folders = group_media_by_depth(media, args)

    if getattr(args, "hide_deleted", False):
        folders = [d for d in folders if d["total"] != d["deleted"]]  # remove folders where all deleted

    if args.depth and media is None:
        folders = reaggregate_at_depth(args, folders)

    if getattr(args, "only_deleted", False):
        if args.folder_sizes:
            folders = [d for d in folders if args.folder_sizes(d["deleted_size"])]
        if args.file_counts:
            folders = [d for d in folders if args.file_counts(d["deleted"])]
    else:
        if args.folder_sizes:
            folders = [d for d in folders if args.folder_sizes(d["size"])]
        if args.file_counts:
            folders = [d for d in folders if args.file_counts(d["exists"])]

    if args.folder_counts:
        folders = [d for d in folders if args.folder_counts(d["folders"])]

    return folders


def collect_media(args) -> list[dict]:
    if args.database:
        media = list(args.db.query(*sqlgroups.fs_sql(args, args.limit)))
    else:
        if getattr(args, "hide_deleted", False):
            args.paths = file_utils.filter_deleted(args.paths)
        media = shell_utils.gen_d(args)

        media = filter_engine.filter_items_by_criteria(args, media)
        media = [d if "size" in d else file_utils.get_file_stats(d) for d in media]

    return media


def big_dirs() -> None:
    args = parse_args()
    media = collect_media(args)

    used_clusters = False
    if args.cluster_sort and len(media) > MIN_CLUSTER_MEDIA:
        used_clusters = True
        from library.text.cluster_sort import cluster_paths

        groups = cluster_paths(args, [d["path"] for d in media])
        groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_path"])))

        media_keyed = {d["path"]: d for d in media}
        folders = [
            {
                "path": group["common_path"],
                "total": len(group["grouped_paths"]),
                "played": sum(bool(media_keyed[s].get("time_played")) for s in group["grouped_paths"]),
                "exists": sum(not bool(media_keyed[s].get("time_deleted")) for s in group["grouped_paths"]),
                "deleted": sum(bool(media_keyed[s].get("time_deleted")) for s in group["grouped_paths"]),
                "deleted_size": sum(
                    media_keyed[s].get("size") or 0
                    for s in group["grouped_paths"]
                    if bool(media_keyed[s].get("time_deleted"))
                ),
                "size": sum(
                    media_keyed[s].get("size") or 0
                    for s in group["grouped_paths"]
                    if not bool(media_keyed[s].get("time_deleted"))
                ),
                "median_size": nums.safe_median(
                    media_keyed[s].get("size")
                    for s in group["grouped_paths"]
                    if not bool(media_keyed[s].get("time_deleted"))
                ),
                "duration": sum(
                    media_keyed[s].get("duration") or 0
                    for s in group["grouped_paths"]
                    if not bool(media_keyed[s].get("time_deleted"))
                ),
                "median_duration": nums.safe_median(
                    media_keyed[s].get("duration")
                    for s in group["grouped_paths"]
                    if not bool(media_keyed[s].get("time_deleted"))
                ),
            }
            for group in groups
        ]
    elif args.parents:
        folders = group_files_by_parents(media)
    else:
        folders = group_files_by_parent(media)

    folders = mcda.group_sort_by(args, folders)
    media = process_big_dirs(args, folders, None if used_clusters else media)

    if args.limit:
        media = media[-int(args.limit) :]
    media = iterables.list_dict_filter_bool(media, keep_0=False)
    media_printer.media_printer(args, media, units="folders")
