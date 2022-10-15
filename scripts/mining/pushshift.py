import argparse, json, sys
from pathlib import Path

from xklb import db, praw_extract, utils
from xklb.utils import log


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library " + action, usage=usage)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("database", nargs="?", default="pushshift.db")
    args = parser.parse_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args

def pushshift_extract(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        "pushshift",
        usage="""library pushshift [database] < stdin

    Download data (about 600GB jsonl.zst; 6TB uncompressed)

        wget -e robots=off -r -k -A zst https://files.pushshift.io/reddit/submissions/

    Load data from files via unzstd

        unzstd --memory=2048MB --stdout RS_2005-07.zst | lb pushshift pushshift.db

    Or multiple:

        for f in files.pushshift.io/reddit/submissions/*.zst
            echo "$f"
            unzstd --memory=2048MB --stdout "$f" | lb pushshift pushshift.db
        end
    """,
    )

    for l in sys.stdin:
        l = l.rstrip("\n")
        if l in ["", '""', "\n"]:
            continue

        post_dict = json.loads(l)
        praw_extract.save_post(args, post_dict, None)

    if not args.db["media"].detect_fts():
        db.optimize(args)
