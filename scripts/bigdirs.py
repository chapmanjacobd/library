import argparse
from typing import List

from tabulate import tabulate

from xklb import db, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sort-by-deleted", action="store_true")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default="4000")
    parser.add_argument("--depth", "-d", default=0, type=int, help="Depth of folders")
    parser.add_argument("--lower", type=int, help="Number of files per folder lower limit")
    parser.add_argument("--upper", type=int, help="Number of files per folder upper limit")
    parser.add_argument(
        "--size", "-S", action="append", help="Only include files of specific sizes (uses the same syntax as fd-find)"
    )
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    args = parser.parse_args()
    args.db = db.connect(args)

    if args.size:
        args.size = utils.parse_human_to_sql(utils.human_to_bytes, "size", args.size)

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def group_files_by_folder(args, media):
    d = {}
    for m in media:
        p = m["path"].split("/")
        while len(p) >= 2:
            p.pop()
            parent = "/".join(p) + "/"

            file_exists = (m.get("time_deleted") or 0) == 0

            if d.get(parent):
                d[parent]["size"] += m["size"] if file_exists else 0
                d[parent]["count"] += 1 if file_exists else 0
                d[parent]["count_deleted"] += 0 if file_exists else 1
            else:
                d[parent] = {
                    "size": m["size"] if file_exists else 0,
                    "count": 1 if file_exists else 0,
                    "count_deleted": 0 if file_exists else 1,
                }

    for path, pdict in list(d.items()):
        if pdict["count"] == 0:
            d.pop(path)
        elif not args.depth:
            if pdict["count"] < (args.lower or 4):
                d.pop(path)
            elif pdict["count"] > (args.upper or 4000):
                d.pop(path)

    return [{**v, "path": k} for k, v in d.items()]


def group_folders(args, folders):
    d = {}
    for f in folders:
        p = f["path"].split("/")
        p.pop()

        depth = 1 + args.depth
        parent = "/".join(p[:depth]) + "/"
        if len(p) < depth:
            continue

        if d.get(parent):
            d[parent]["size"] += f["size"]
            d[parent]["count"] += f["count"]
            d[parent]["count_deleted"] += f["count_deleted"]
        else:
            d[parent] = f

    for path, pdict in list(d.items()):
        if args.lower and pdict["count"] < args.lower:
            d.pop(path)
        elif args.upper and pdict["count"] > args.upper:
            d.pop(path)

    return [{**v, "path": k} for k, v in d.items()]


def get_table(args) -> List[dict]:
    columns = args.db["media"].columns_dict

    media = list(
        args.db.query(
            f"""
        select
            path
            , size
            {', time_deleted' if 'time_deleted' in columns else ''}
        from media
        where 1=1
            {'and time_downloaded > 0' if 'time_downloaded' in columns else ''}
            {args.size if args.size else ''}
        order by path
        """
        )
    )
    return media


def process_bigdirs(args, media):
    folders = group_files_by_folder(args, media)
    if args.depth:
        folders = group_folders(args, folders)
    return sorted(folders, key=lambda x: x["count_deleted"] if args.sort_by_deleted else x["size"] / x["count"])


def bigdirs() -> None:
    args = parse_args()
    tbl = get_table(args)
    tbl = process_bigdirs(args, tbl)

    if args.limit:
        tbl = tbl[-int(args.limit) :]

    tbl = utils.list_dict_filter_bool(tbl, keep_0=False)
    tbl = utils.col_resize(tbl, "path", 60)
    tbl = utils.col_naturalsize(tbl, "size")
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))
    if not args.limit:
        print(f"{len(tbl)} folders found")


if __name__ == "__main__":
    bigdirs()
