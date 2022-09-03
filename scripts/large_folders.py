import argparse

import humanize
import pandas as pd
from tabulate import tabulate

from xklb import db
from xklb.utils import resize_col

parser = argparse.ArgumentParser()
parser.add_argument("database")
parser.add_argument("--verbose", "-v", action="count", default=0)
args = parser.parse_args()
args.db = db.connect(args)

db_resp = pd.DataFrame(args.db.query("select path, size from media order by path"))  # type: ignore

d = {}
for m in db_resp.to_dict(orient="records"):
    p = m["path"].split("/")
    while len(p) > 2:
        p.pop()
        parent = "/".join(p) + '/'

        if d.get(parent):
            d[parent]["size"] += m["size"]
            d[parent]["count"] += 1
        else:
            d[parent] = dict(size=m["size"], count=1)

for path, pdict in list(d.items()):
    if pdict["count"] < 35 or pdict["count"] > 3500:
        d.pop(path)

tbl = pd.DataFrame([{**v, "path": k} for k, v in d.items()]).sort_values(by=['size'])

tbl[["size"]] = tbl[["size"]].applymap(lambda x: None if x is None else humanize.naturalsize(x))
tbl = resize_col(tbl, "path", 60)

print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore
