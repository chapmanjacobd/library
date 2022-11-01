import argparse
from pathlib import Path

from xklb import db, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("dbs_folder")
    parser.add_argument("--database", "--db", "-db", default=":memory:")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def reddit_dbs() -> None:
    args = parse_args()
    dbs = Path(args.dbs_folder).glob("*.db")

    attach_dbs = ['ATTACH DATABASE "' + str(db.resolve()) + '" AS d' + str(i) for i, db in enumerate(dbs)]
    args.db.executescript(";".join(attach_dbs))

    d = args.db.query(
        "select count(*) from (" + "".join(["select * from d" + str(i) for i, db in enumerate(dbs)]) + ")"
    )

    raise


""" todo:
1. export list of all subreddits with metadata, including start date
2. for each subreddit create a media database

Upload to Zenodo
"""

if __name__ == "__main__":
    reddit_dbs()
