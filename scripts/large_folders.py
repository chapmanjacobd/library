import argparse
from typing import List

from tabulate import tabulate

from xklb import db, utils
from xklb.utils import log


def group_by_folder(args, media):
    d = {}
    for m in media:
        p = m["path"].split("/")
        while len(p) >= 3:
            p.pop()
            parent = "/".join(p) + "/"

            if d.get(parent):
                d[parent]["size"] += m["size"]
                d[parent]["count"] += 1
            else:
                d[parent] = dict(size=m["size"], count=1)

    for path, pdict in list(d.items()):
        if pdict["count"] < args.lower or pdict["count"] > args.upper:
            d.pop(path)

    return [{**v, "path": k} for k, v in d.items()]


def get_table(args) -> List[dict]:
    columns = args.db["media"].columns_dict

    media = list(
        args.db.query(
            f"""
        select path, size
        from media
        where 1=1
            {'and time_deleted = 0' if 'time_deleted' in columns else ''}
            {'and time_downloaded > 0' if 'time_downloaded' in columns else ''}
        order by path
        """
        )
    )

    folders = group_by_folder(args, media)
    return sorted(folders, key=lambda x: x["size"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default="4000")
    parser.add_argument("--lower", default=4, type=int, help="Number of files per folder lower limit")
    parser.add_argument("--upper", default=4000, type=int, help="Number of files per folder upper limit")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def large_folders() -> None:
    args = parse_args()
    tbl = get_table(args)

    if args.limit:
        tbl = tbl[-int(args.limit) :]

    tbl = utils.col_resize(tbl, "path", 60)
    tbl = utils.col_naturalsize(tbl, "size")
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))
    if not args.limit:
        print(f"{len(tbl)} folders found")


if __name__ == "__main__":
    large_folders()
