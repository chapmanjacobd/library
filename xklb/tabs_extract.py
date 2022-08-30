import argparse, sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from xklb import db, utils
from xklb.paths import Frequency, sanitize_url
from xklb.player import remove_media
from xklb.utils import argparse_enum, log


def parse_args():
    parser = argparse.ArgumentParser(
        prog="lb tabsadd",
        usage=r"""lb tabsadd --frequency {daily,weekly,monthly,quarterly,yearly} --category CATEGORY [--no-sanitize] [database] paths ...

    Adding one URL:

        lb tabsadd -f monthly -c travel ~/lb/tabs.db https://old.reddit.com/r/Colombia/top/?sort=top&t=month

        Depending on your shell you may need to escape the URL (add quotes)

        If you use Fish shell know that you can enable features to make pasting easier:
            set -U fish_features stderr-nocaret qmark-noglob regex-easyesc ampersand-nobg-in-token

        Also I recommend turning Ctrl+Backspace into a super-backspace for repeating similar commands with long args:
            echo 'bind \b backward-kill-bigword' >> ~/.config/fish/config.fish

    Importing from a line-delimitated file:

        lb tabsadd -f yearly -c reddit ~/lb/tabs.db (cat ~/mc/yearly-subreddit.cron)

""",
    )
    parser.add_argument("database", nargs="?", default="tabs.db")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument(
        "--frequency",
        "--freqency",
        "-f",
        default=Frequency.Monthly,
        type=Frequency,
        action=argparse_enum,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)
    parser.add_argument("--no-sanitize", "-s", action="store_false", help="Don't sanitize some common URL parameters")

    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def get_new_paths(args):
    if not args.no_sanitize:
        args.paths = [sanitize_url(args, path) for path in args.paths]

    if args.category is None:
        qb = (
            "select path from media where path in (" + ",".join(["?"] * len(args.paths)) + ")",
            (*args.paths,),
        )
    else:
        qb = (
            "select path from media where category = ? and path in (" + ",".join(["?"] * len(args.paths)) + ")",
            (args.category, *args.paths),
        )

    try:
        existing = set([d["path"] for d in args.db.query(*qb)])
    except Exception:
        pass
    else:
        if len(existing) > 0:
            print(f"Updating frequency for {len(existing)} existing paths")
            remove_media(args, list(existing), quiet=True)

    args.paths = utils.conform([path.strip() for path in args.paths])
    return args.paths


def extract_url_metadata(args, path):
    hostname = urlparse(path).hostname or ""

    return dict(
        path=path,
        hostname=hostname,
        frequency=args.frequency.value,
        category=args.category,
        time_created=int(datetime.utcnow().timestamp()),
        time_played=0,
        play_count=0,
    )


def tabs_add(args=None):
    if args:
        sys.argv[1:] = args
    args = parse_args()

    tabsDF = pd.DataFrame([extract_url_metadata(args, path) for path in get_new_paths(args)])
    tabsDF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
        "media",
        con=args.db.conn,
        if_exists="append",
        index=False,
        chunksize=70,
        method="multi",
    )
