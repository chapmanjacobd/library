import argparse, os
from collections import defaultdict
from pathlib import Path

from xklb import media_printer, usage
from xklb.tablefiles import mcda
from xklb.utils import arg_utils, arggroups, argparse_utils, consts, file_utils, iterables, nums


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(
        prog="library big_dirs",
        usage=usage.big_dirs,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arggroups.cluster(parser)
    arggroups.group_folders(parser)
    parser.set_defaults(limit="4000", lower=4, depth=0)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = consts.SC.big_dirs
    arggroups.args_post(args, parser)

    arggroups.group_folders_post(args)

    return args


def filter_deleted(args, d):
    for path, pdict in list(d.items()):
        if pdict["exists"] == 0:
            d.pop(path)

    if args.folder_counts and not args.depth:
        for path, pdict in list(d.items()):
            if not args.folder_counts(pdict["exists"]):
                d.pop(path)


def group_files_by_parents(args, media) -> list[dict]:
    p_media = {}
    min_parts = 10
    for m in media:
        p = m["path"].split(os.sep)
        min_parts = min(min_parts, len(p))
        while len(p) >= 2:
            p.pop()
            parent = os.sep.join(p) + os.sep

            if parent not in p_media:
                p_media[parent] = []
            else:
                p_media[parent].append(m)

    d = {}
    for parent, media in list(p_media.items()):
        d[parent] = {
            "size": sum(m.get("size") or 0 for m in media if not bool(m.get("time_deleted"))),
            "median_size": nums.safe_median(m.get("size") or 0 for m in media if not bool(m.get("time_deleted"))),
            "duration": sum(m.get("duration") or 0 for m in media if not bool(m.get("time_deleted"))),
            "median_duration": nums.safe_median(
                m.get("duration") or 0 for m in media if not bool(m.get("time_deleted"))
            ),
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

    filter_deleted(args, d)

    return [{**v, "path": k} for k, v in d.items()]


def group_files_by_parent(args, media) -> list[dict]:
    p_media = defaultdict(list)
    for m in media:
        p_media[str(Path(m["path"]).parent)].append(m)

    d = {}
    for parent, media in list(p_media.items()):
        d[parent] = {
            "size": sum(m.get("size") or 0 for m in media if not bool(m.get("time_deleted"))),
            "median_size": nums.safe_median(m.get("size") or 0 for m in media if not bool(m.get("time_deleted"))),
            "duration": sum(m.get("duration") or 0 for m in media if not bool(m.get("time_deleted"))),
            "median_duration": nums.safe_median(
                m.get("duration") or 0 for m in media if not bool(m.get("time_deleted"))
            ),
            "total": len(media),
            "exists": sum(not bool(m.get("time_deleted")) for m in media),
            "deleted": sum(bool(m.get("time_deleted")) for m in media),
            "deleted_size": sum(m.get("size") or 0 for m in media if bool(m.get("time_deleted"))),
            "deleted_duration": sum(m.get("duration") or 0 for m in media if bool(m.get("time_deleted"))),
            "played": sum(bool(m.get("time_last_played")) for m in media),
        }

    filter_deleted(args, d)

    return [{**v, "path": k} for k, v in d.items()]


def folder_depth(args, folders) -> list[dict]:
    d = {}
    for f in folders:
        p = f["path"].split(os.sep)
        p.pop()

        depth = 1 + args.depth
        parent = os.sep.join(p[:depth]) + os.sep
        if len(p) < depth:
            continue

        if d.get(parent):
            d[parent]["size"] += f["size"]
            d[parent]["duration"] += f["duration"]
            d[parent]["total"] += f["total"]
            d[parent]["exists"] += f["exists"]
            d[parent]["deleted"] += f["deleted"]
            d[parent]["played"] += f["played"]
        else:
            d[parent] = f

    if args.folder_counts:
        for path, pdict in list(d.items()):
            if not args.folder_counts(pdict["exists"]):
                d.pop(path)

    return [{**v, "path": k} for k, v in d.items()]


def process_big_dirs(args, folders) -> list[dict]:
    folders = [d for d in folders if d["total"] != d["deleted"]]  # remove folders where all deleted

    if args.depth:
        folders = folder_depth(args, folders)
    if args.folder_sizes:
        folders = [d for d in folders if args.folder_sizes(d["size"])]

    return folders


def big_dirs() -> None:
    args = parse_args()

    media = list(arg_utils.gen_d(args))
    media = [d if "size" in d else file_utils.get_filesize(d) for d in media]
    if args.cluster_sort and len(media) > 2:
        from xklb.text.cluster_sort import cluster_paths

        groups = cluster_paths([d["path"] for d in media], n_clusters=getattr(args, "clusters", None))
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
                    media_keyed[s].get("size") or 0
                    for s in group["grouped_paths"]
                    if not bool(media_keyed[s].get("time_deleted"))
                ),
                "duration": sum(
                    media_keyed[s].get("duration") or 0
                    for s in group["grouped_paths"]
                    if not bool(media_keyed[s].get("time_deleted"))
                ),
                "median_duration": nums.safe_median(
                    media_keyed[s].get("duration") or 0
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


if __name__ == "__main__":
    big_dirs()
