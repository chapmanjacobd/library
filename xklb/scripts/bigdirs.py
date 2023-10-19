import argparse, os
from pathlib import Path
from typing import Dict, List

from xklb import history, usage
from xklb.media import media_printer
from xklb.utils import consts, db_utils, file_utils, nums, objects, sql_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library bigdirs",
        usage=usage.bigdirs,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--sort-by", "--sort", "-u")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default="4000")
    parser.add_argument("--depth", "-d", default=0, type=int, help="Depth of folders")
    parser.add_argument("--lower", type=int, default=4, help="Minimum number of files per folder")
    parser.add_argument("--upper", type=int, help="Maximum number of files per folder")
    parser.add_argument(
        "--folder-size",
        "--foldersize",
        "-Z",
        action="append",
        help="Only include folders of specific sizes (uses the same syntax as fd-find)",
    )
    parser.add_argument(
        "--size",
        "-S",
        action="append",
        help="Only include files of specific sizes (uses the same syntax as fd-find)",
    )
    parser.add_argument("--include", "-s", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--cluster-sort", action="store_true", help="Cluster by filename instead of grouping by folder")
    parser.add_argument("--clusters", "--n-clusters", "-c", type=int, help="Number of KMeans clusters")
    parser.add_argument("--print", "-p", default="", const="p", nargs="?")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.db = db_utils.connect(args)

    args.include += args.search
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if len(args.include) == 1 and os.sep in args.include[0]:
        args.include = [file_utils.resolve_absolute_path(args.include[0])]

    if args.size:
        args.size = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", args.size)

    args.action = consts.SC.bigdirs
    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def group_files_by_folder(args, media) -> List[Dict]:
    d = {}
    for m in media:
        p = m["path"].split(os.sep)
        while len(p) >= 2:
            p.pop()
            parent = os.sep.join(p) + os.sep

            file_deleted = bool(m.get("time_deleted", 0))
            file_played = bool(m.get("time_played", 0))
            if parent not in d:
                d[parent] = {"size": 0, "count": 0, "deleted": 0, "played": 0}
            if not file_deleted:
                d[parent]["size"] += m.get("size") or 0
                d[parent]["count"] += 1
            else:
                d[parent]["deleted"] += 1
            if file_played:
                d[parent]["played"] += 1

    for path, pdict in list(d.items()):
        if pdict["count"] == 0:
            d.pop(path)
        elif not args.depth:
            if args.lower and pdict["count"] < args.lower:
                d.pop(path)
            elif args.upper and pdict["count"] > args.upper:
                d.pop(path)

    return [{**v, "path": k} for k, v in d.items()]


def folder_depth(args, folders) -> List[Dict]:
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
            d[parent]["count"] += f["count"]
            d[parent]["deleted"] += f["deleted"]
            d[parent]["played"] += f["played"]
        else:
            d[parent] = f

    for path, pdict in list(d.items()):
        if args.lower is not None and pdict["count"] < args.lower:
            d.pop(path)
        elif args.upper is not None and pdict["count"] > args.upper:
            d.pop(path)

    return [{**v, "path": k} for k, v in d.items()]


def get_table(args) -> List[dict]:
    m_columns = db_utils.columns(args, "media")
    args.filter_sql = []
    args.filter_bindings = {}

    if args.size:
        args.filter_sql.append(" and size IS NOT NULL " + args.size)
    db_utils.construct_search_bindings(
        args,
        [f"m.{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
    )

    media = list(
        args.db.query(
            f"""
        SELECT
            path
            , size
            {', time_deleted' if 'time_deleted' in m_columns else ''}
            , MAX(h.time_played) time_played
        FROM media m
        LEFT JOIN history h on h.media_id = m.id
        WHERE 1=1
            {'and time_downloaded > 0' if 'time_downloaded' in m_columns else ''}
            {" ".join(args.filter_sql)}
        GROUP BY m.id
        ORDER BY path
        """,
            args.filter_bindings,
        ),
    )
    return media


def sort_by(args):
    if args.sort_by:
        if args.sort_by == "played_ratio":
            return lambda x: x["played"] / x["deleted"] if x["deleted"] else 0
        elif args.sort_by == "deleted_ratio":
            return lambda x: x["deleted"] / x["played"] if x["played"] else 0
        else:
            return lambda x: x[args.sort_by]

    return lambda x: x["size"] / x["count"]


def process_bigdirs(args, folders) -> List[Dict]:
    folders = [d for d in folders if d["deleted"] != d["count"]]  # remove folders where all deleted

    if args.depth:
        folders = folder_depth(args, folders)
    if args.folder_size:
        args.folder_size = sql_utils.parse_human_to_lambda(nums.human_to_bytes, args.folder_size)
        folders = [d for d in folders if args.folder_size(d["size"])]

    reverse = False
    if args.sort_by and " desc" in args.sort_by:
        args.sort_by = args.sort_by.replace(" desc", "")
        reverse = True

    return sorted(folders, key=sort_by(args), reverse=reverse)


def bigdirs() -> None:
    args = parse_args()
    history.create(args)

    media = get_table(args)
    if args.cluster_sort and len(media) > 2:
        from xklb.scripts.cluster_sort import cluster_paths

        groups = cluster_paths([d["path"] for d in media], n_clusters=getattr(args, "clusters", None))
        groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_prefix"])))

        media_keyed = {d["path"]: d for d in media}
        folders = [
            {
                "path": group["common_prefix"],
                "count": len(group["grouped_paths"]),
                "size": sum(media_keyed[s].get("size", 0) for s in group["grouped_paths"]),
                "played": sum(bool(media_keyed[s].get("time_played", 0)) for s in group["grouped_paths"]),
                "deleted": sum(bool(media_keyed[s].get("time_deleted", 0)) for s in group["grouped_paths"]),
            }
            for group in groups
        ]
    else:
        folders = group_files_by_folder(args, media)
    media = process_bigdirs(args, folders)

    if args.limit:
        media = media[-int(args.limit) :]

    media_printer.media_printer(args, media, units="folders")


if __name__ == "__main__":
    bigdirs()
