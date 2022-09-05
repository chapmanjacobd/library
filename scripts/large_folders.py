import argparse

import humanize
from tabulate import tabulate

from xklb import db, utils


def get_table(args):
    db_resp = list(
        args.db.query(
            """
        select path, size
        from media
        where is_deleted = 0
        order by path
        """
        )
    )

    d = {}
    for m in db_resp:
        p = m["path"].split("/")
        while len(p) > 2:
            p.pop()
            parent = "/".join(p) + "/"

            if d.get(parent):
                d[parent]["size"] += m["size"]
                d[parent]["count"] += 1
            else:
                d[parent] = dict(size=m["size"], count=1)

    for path, pdict in list(d.items()):
        if pdict["count"] < 35 or pdict["count"] > 3500:
            d.pop(path)

    d = [{**v, "path": k} for k, v in d.items()]

    return sorted(d, key=lambda x: x["size"])


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.db = db.connect(args)
    return args


def large_folders():
    args = parse_args()
    tbl = get_table(args)

    if args.limit:
        tbl = tbl[-int(args.limit) :]

    tbl = utils.col_resize(tbl, "path", 60)
    tbl = utils.col_naturalsize(tbl, "size")
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore
    if not args.limit:
        print(f"{len(tbl)} folders found")


if __name__ == "__main__":
    large_folders()
