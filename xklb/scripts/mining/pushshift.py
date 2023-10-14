import argparse, sys
from pathlib import Path

from xklb import usage
from xklb.reddit_extract import slim_post_data
from xklb.utils import db_utils, objects, printing
from xklb.utils.log_utils import log

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
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def save_data(args, reddit_posts, media) -> None:
    if len(reddit_posts) > 0:
        args.db["reddit_posts"].insert_all(reddit_posts, alter=True)
        reddit_posts.clear()
    if len(media) > 0:
        args.db["media"].insert_all(media, alter=True)
        media.clear()


def pushshift_extract(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args("pushshift", usage=usage.pushshift)

    args.db.enable_wal()

    count = 0
    reddit_posts = []
    media = []
    for line in sys.stdin:
        line = line.rstrip("\n")
        if line in ["", '""', "\n"]:
            continue

        try:
            post_dict = orjson.loads(line)
        except Exception:
            log.warning("Skipping unreadable line: %s", line)
            continue

        slim_dict = objects.dict_filter_bool(slim_post_data(post_dict, post_dict.get("subreddit")))
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
            printing.print_overwrite(f"Processing {count}")
            save_data(args, reddit_posts, media)

    save_data(args, reddit_posts, media)
    print("\n")
