import argparse, os
from collections import defaultdict
from pathlib import Path

from library import usage
from library.fsdb import files_info
from library.fsdb.disk_usage import check_depth, count_folders, format_folder
from library.playback import media_printer
from library.tablefiles import mcda
from library.utils import arggroups, argparse_utils, file_utils, iterables, nums, sqlgroups


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.big_dirs)
    arggroups.sql_fs(parser)
    arggroups.files(parser)

    arggroups.text_filtering(parser)
    arggroups.cluster_sort(parser)
    arggroups.group_folders(parser)
    arggroups.debug(parser)

    arggroups.database_or_paths(parser, destination=True)
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.files_post(args)
    arggroups.sql_fs_post(args)
    arggroups.group_folders_post(args)

    return args


def group_files_by_parents(args, media) -> list[dict]:
    p_media = {}
    min_parts = 10
    for m in media:
        p = m["path"].split(os.sep)
        min_parts = min(min_parts, len(p))
        while len(p) >= 2:
            p.pop()
            parent = os.sep.join(p)

            if parent not in p_media:
                p_media[parent] = [m]
            else:
                p_media[parent].append(m)

    d = {}
    for parent, media in list(p_media.items()):
        d[parent] = {
            "size": sum(m.get("size") or 0 for m in media if not bool(m.get("time_deleted"))),
            "median_size": nums.safe_median(m.get("size") for m in media if not bool(m.get("time_deleted"))),
            "duration": sum(m.get("duration") or 0 for m in media if not bool(m.get("time_deleted"))),
            "median_duration": nums.safe_median(m.get("duration") for m in media if not bool(m.get("time_deleted"))),
            "total": len(media),
            "exists": sum(not bool(m.get("time_deleted")) for m in media),
            "deleted": sum(bool(m.get("time_deleted")) for m in media),
            "deleted_size": sum(m.get("size") or 0 for m in media if bool(m.get("time_deleted"))),
            "deleted_duration": sum(m.get("duration") or 0 for m in media if bool(m.get("time_deleted"))),
            "played": sum(bool(m.get("time_last_played")) for m in media),
        }

    for parent, _ in list(d.items()):
        if len(parent.split(os.sep)) < min_parts:
            d.pop(parent)

    parents = set(d.keys())
    subdirectory_count = count_folders(parents)
    for parent, data in d.items():
        data["folders"] = subdirectory_count[parent]

    return [{**v, "path": format_folder(k)} for k, v in d.items()]


def group_files_by_parent(args, media) -> list[dict]:
    p_media = defaultdict(list)
    for m in media:
        p_media[str(Path(m["path"]).parent)].append(m)

    d = {}
    for parent, media in list(p_media.items()):
        d[parent] = {
            "total": len(media),
            "duration": sum(m.get("duration") or 0 for m in media if not bool(m.get("time_deleted"))),
            "median_duration": nums.safe_median(m.get("duration") for m in media if not bool(m.get("time_deleted"))),
            "size": sum(m.get("size") or 0 for m in media if not bool(m.get("time_deleted"))),
            "median_size": nums.safe_median(m.get("size") for m in media if not bool(m.get("time_deleted"))),
            "played": sum(bool(m.get("time_last_played")) for m in media),
            "exists": sum(not bool(m.get("time_deleted")) for m in media),
            "deleted": sum(bool(m.get("time_deleted")) for m in media),
            "deleted_size": sum(m.get("size") or 0 for m in media if bool(m.get("time_deleted"))),
            "deleted_duration": sum(m.get("duration") or 0 for m in media if bool(m.get("time_deleted"))),
        }

    return [{"path": format_folder(k), **v} for k, v in d.items()]


def reaggregate_at_depth(args, folders) -> list[dict]:
    d = {}
    for f in folders:
        p = f["path"].rstrip(os.sep).split(os.sep)

        if args.max_depth:
            p = p[: args.max_depth]
        if not check_depth(args, len(p)):
            continue

        parent = os.sep.join(p) + os.sep
        if d.get(parent):
            d[parent]["size"] += f["size"]
            d[parent]["duration"] += f["duration"]
            d[parent]["total"] += f["total"]
            d[parent]["exists"] += f["exists"]
            d[parent]["deleted"] += f["deleted"]
            d[parent]["played"] += f["played"]
            d[parent]["folders"] += f["folders"]
        else:
            d[parent] = f

    return [{**v, "path": format_folder(k)} for k, v in d.items()]


def process_big_dirs(args, folders) -> list[dict]:
    if args.hide_deleted:
        folders = [d for d in folders if d["total"] != d["deleted"]]  # remove folders where all deleted

    if args.depth:
        folders = reaggregate_at_depth(args, folders)

    if args.only_deleted:
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
        if args.hide_deleted:
            args.paths = file_utils.filter_deleted(args.paths)
        media = file_utils.gen_d(args)

        media = files_info.filter_files_by_criteria(args, media)
        media = [d if "size" in d else file_utils.get_file_stats(d) for d in media]

    return media


def big_dirs() -> None:
    args = parse_args()
    media = collect_media(args)

    if args.cluster_sort and len(media) > 2:
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
        folders = group_files_by_parents(args, media)
    else:
        folders = group_files_by_parent(args, media)

    folders = mcda.group_sort_by(args, folders)
    media = process_big_dirs(args, folders)

    if args.limit:
        media = media[-int(args.limit) :]
    media = iterables.list_dict_filter_bool(media, keep_0=False)
    media_printer.media_printer(args, media, units="folders")
