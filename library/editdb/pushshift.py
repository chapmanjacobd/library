import argparse, sys

from library.createdb.reddit_add import slim_post_data
from library.utils import arggroups, argparse_utils, objects, printing
from library.utils.log_utils import log

USAGE = {
    'pushshift': """library database import pushshift DATABASE < stdin

    Download data (about 600GB jsonl.zst; 6TB uncompressed)

        wget -e robots=off -r -k -A zst https://files.pushshift.io/reddit/submissions/

    Load data from files via unzstd

        unzstd --memory=2048MB --stdout RS_2005-07.zst | library database import pushshift pushshift.db

    Or multiple (output is about 1.5TB SQLite fts-searchable)

        for f in psaw/files.pushshift.io/reddit/submissions/*.zst
            echo "unzstd --memory=2048MB --stdout $f | library database import pushshift (basename $f).db"
            library database optimize (basename $f).db
        end | parallel -j5
""",
}

try:
    import orjson
except ModuleNotFoundError:
    import json as orjson


def parse_args(usage) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser, create_db=True)

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

    args = parse_args(usage=USAGE['pushshift'])

    args.db.enable_wal()

    count = 0
    reddit_posts = []
    media = []
    print("library pushshift: Reading from stdin...", file=sys.stderr)
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
