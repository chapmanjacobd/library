import argparse

import humanize
import pandas as pd
from tabulate import tabulate

from xklb import db, utils


def get_table(args):
    db_resp = pd.DataFrame(
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
    for m in db_resp.to_dict(orient="records"):
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

    return pd.DataFrame([{**v, "path": k} for k, v in d.items()]).sort_values(by=["size"])


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
        tbl = tbl.tail(int(args.limit))

    tbl[["size"]] = tbl[["size"]].applymap(lambda x: None if x is None else humanize.naturalsize(x))
    tbl = utils.resize_col(tbl, "path", 60)
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore
    if not args.limit:
        print(f"{len(tbl)} folders found")


if __name__ == "__main__":
    large_folders()
