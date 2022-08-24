import argparse
import enum
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from xklb.db import fetchall_dict, sqlite_con
from xklb.utils import argparse_enum, filter_None, log, single_column_tolist
from xklb.utils_player import remove_media


class Frequency(enum.Enum):
    Daily = "daily"
    Weekly = "weekly"
    Monthly = "monthly"
    Quarterly = "quarterly"
    Yearly = "yearly"


def reddit_frequency(frequency: Frequency):
    mapper = {
        Frequency.Daily: "day",
        Frequency.Weekly: "week",
        Frequency.Monthly: "month",
        Frequency.Quarterly: "year",
        Frequency.Yearly: "year",
    }

    return mapper.get(frequency, "month")


def sanitize_url(args, path):
    matches = re.match(r".*reddit.com/r/(.*?)/.*", path)
    if matches:
        subreddit = matches.groups()[0]
        return "https://old.reddit.com/r/" + subreddit + "/top/?sort=top&t=" + reddit_frequency(args.frequency)

    return path


def parse_args():
    parser = argparse.ArgumentParser(
        prog="lb tabsadd",
        usage=r"""lb tabsadd --frequency {daily,weekly,monthly,quarterly,yearly} --category CATEGORY [--sanitize] [database] paths ...

    Adding one URL:

        lb tabsadd -f monthly -c travel --sanitize ~/lb/tabs.db https://old.reddit.com/r/Colombia/top/?sort=top&t=month

        Depending on your shell you may need to escape the URL (add quotes)

        If you use Fish shell know that you can enable features to make pasting easier:
            set -U fish_features stderr-nocaret qmark-noglob regex-easyesc ampersand-nobg-in-token

        Also I recommend turning Ctrl+Backspace into a super-backspace for repeating similar commands with long args:
            echo 'bind \b backward-kill-bigword' >> ~/.config/fish/config.fish

    Importing from a line-delimitated file:

        lb tabsadd -f yearly -c reddit --sanitize ~/lb/tabs.db (cat ~/mc/yearly-subreddit.cron)

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
    parser.add_argument("--sanitize", "-s", action="store_true", help="Sanitize some common URL parameters")

    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    log.info(filter_None(args.__dict__))

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.con = sqlite_con(args.database)

    return args


def get_new_paths(args):
    if args.sanitize:
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
        existing = set(single_column_tolist(fetchall_dict(args.con, *qb), "path"))
    except Exception:
        pass
    else:
        if len(existing) > 0:
            print(f"Updating frequency for {len(existing)} existing paths")
            remove_media(args, list(existing), quiet=True)

    args.paths = list(filter(bool, [path.strip() for path in args.paths]))
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
        con=args.con,
        if_exists="append",
        index=False,
        chunksize=70,
        method="multi",
    )
