import argparse, sys
from pathlib import Path

from xklb import db, utils
from xklb.praw_extract import slim_post_data
from xklb.utils import log

try:
    import orjson
except ModuleNotFoundError:
    import json as orjson


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library " + action, usage=usage)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    args = parser.parse_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def save_data(args, reddit_posts, media):
    if len(reddit_posts) > 0:
        args.db["reddit_posts"].insert_all(reddit_posts, alter=True)
        reddit_posts.clear()
    if len(media) > 0:
        args.db["media"].insert_all(media, alter=True)
        media.clear()


def pushshift_extract(args=None) -> None:
    if args:
        sys.argv = ["lb"] + args

    args = parse_args(
        "pushshift",
        usage="""library pushshift [database] < stdin

    Download data (about 600GB jsonl.zst; 6TB uncompressed)

        wget -e robots=off -r -k -A zst https://files.pushshift.io/reddit/submissions/

    Load data from files via unzstd

        unzstd --memory=2048MB --stdout RS_2005-07.zst | library pushshift pushshift.db

    Or multiple (output is about 1.5TB SQLITE fts-searchable):

        for f in psaw/files.pushshift.io/reddit/submissions/*.zst
            echo "unzstd --memory=2048MB --stdout $f | library pushshift (basename $f).db"
            library optimize (basename $f).db
        end | parallel -j5
    """,
    )

    args.db.enable_wal()

    count = 0
    reddit_posts = []
    media = []
    for l in sys.stdin:
        l = l.rstrip("\n")
        if l in ["", '""', "\n"]:
            continue

        try:
            post_dict = orjson.loads(l)
        except Exception:
            print("Skipping unreadable line", l)
            continue

        slim_dict = utils.dict_filter_bool(slim_post_data(post_dict, post_dict.get("subreddit")))
        if slim_dict:
            if "selftext" in slim_dict:
                reddit_posts.append(slim_dict)
            elif "path" in slim_dict:
                media.append(slim_dict)
            else:
                continue

        count += 1
        remainder = count % 1_000_000
        if remainder == 0:
            sys.stdout.write("\033[K\r")
            print("Processing", count, end="\r", flush=True)
            save_data(args, reddit_posts, media)

    save_data(args, reddit_posts, media)
    print("\n")
