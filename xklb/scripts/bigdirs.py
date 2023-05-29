import argparse
from pathlib import Path
from typing import Dict, List

from tabulate import tabulate

from xklb import db, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library bigdirs",
        usage=usage.bigdirs,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--sort-by")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default="4000")
    parser.add_argument("--depth", "-d", default=0, type=int, help="Depth of folders")
    parser.add_argument("--lower", type=int, help="Number of files per folder lower limit")
    parser.add_argument("--upper", type=int, help="Number of files per folder upper limit")
    parser.add_argument(
        "--size",
        "-S",
        action="append",
        help="Only include files of specific sizes (uses the same syntax as fd-find)",
    )
    parser.add_argument("--include", "-s", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.db = db.connect(args)

    args.include += args.search
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if args.size:
        args.size = utils.parse_human_to_sql(utils.human_to_bytes, "size", args.size)

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def group_files_by_folder(args, media) -> List[Dict]:
    d = {}
    for m in media:
        p = m["path"].split("/")
        while len(p) >= 2:
            p.pop()
            parent = "/".join(p) + "/"

            file_deleted = bool(m.get("time_deleted", 0))
            file_played = bool(m.get("time_played", 0))
            if parent not in d:
                d[parent] = {"size": 0, "count": 0, "deleted": 0, "played": 0}
            if not file_deleted:
                d[parent]["size"] += m.get("size", 0)
                d[parent]["count"] += 1
            else:
                d[parent]["deleted"] += 1
            if file_played:
                d[parent]["played"] += 1

    for path, pdict in list(d.items()):
        if pdict["count"] == 0:
            d.pop(path)
        elif not args.depth:
            if pdict["count"] < (args.lower or 4):
                d.pop(path)
            elif pdict["count"] > (args.upper or 4000):
                d.pop(path)

    return [{**v, "path": k} for k, v in d.items()]


def group_folders(args, folders) -> List[Dict]:
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
    m_columns = args.db["media"].columns_dict
    args.filter_sql = []
    args.filter_bindings = {}

    if args.size:
        args.filter_sql.append(" and size IS NOT NULL " + args.size)
    db.construct_search_bindings(args, m_columns)

    media = list(
        args.db.query(
            f"""
        select
            path
            , size
            {', time_deleted' if 'time_deleted' in m_columns else ''}
            {', time_played' if 'time_played' in m_columns else ''}
        from media m
        where 1=1
            {'and time_downloaded > 0' if 'time_downloaded' in m_columns else ''}
            {" ".join(args.filter_sql)}
        order by path
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


def process_bigdirs(args, media) -> List[Dict]:
    folders = group_files_by_folder(args, media)
    if args.depth:
        folders = group_folders(args, folders)
    return sorted(folders, key=sort_by(args))


def bigdirs() -> None:
    args = parse_args()
    tbl = get_table(args)
    tbl = process_bigdirs(args, tbl)

    if args.limit:
        tbl = tbl[-int(args.limit) :]

    tbl = utils.list_dict_filter_bool(tbl, keep_0=False)
    tbl = utils.col_resize(tbl, "path", 50)
    tbl = utils.col_naturalsize(tbl, "size")
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))
    if not args.limit:
        print(f"{len(tbl)} folders found")


if __name__ == "__main__":
    bigdirs()
