import argparse
import enum
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from sqlite3 import OperationalError
from timeit import default_timer as timer
from typing import Dict, List, Union
from urllib.parse import urljoin, urlparse

import pandas as pd

from xklb.db import fetchall_dict, sqlite_con
from xklb.utils import (
    argparse_enum,
    combine,
    filter_None,
    log,
    remove_media,
    safe_unpack,
    single_column_tolist,
)


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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("db", nargs="?", default="tabs.db")
    parser.add_argument("--db", "-db")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--frequency", "-f", default=Frequency.Monthly, type=Frequency, action=argparse_enum)
    parser.add_argument("--category", "-c")
    parser.add_argument("--sanitize", "-s", action="store_true")

    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    log.info(filter_None(args.__dict__))

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.con = sqlite_con(args.database)

    return args


def get_new_paths(args):
    given_paths = set(args.paths)

    try:
        existing = set(
            single_column_tolist(
                fetchall_dict(
                    args.con,
                    "select path from media where category = ? and path in (" + ",".join(["?"] * len(args.paths)) + ")",
                    (
                        args.category,
                        *args.paths,
                    ),
                ),
                "path",
            )
        )
    except Exception:
        pass
    else:
        print(f"Updating frequency for {len(existing)} existing paths")
        remove_media(args, list(existing), quiet=True)

    return list(given_paths)


def sanitize_url(args, path):
    matches = re.match(r".*reddit.com/r/(.*?)/.*", path)
    if matches:
        subreddit = matches.groups()[0]
        return "https://old.reddit.com/r/" + subreddit + "/top/?sort=top&t=" + reddit_frequency(args.frequency)

    return path


def extract_url_metadata(args, path):
    hostname = urlparse(path).hostname or ""
    if args.sanitize:
        path = sanitize_url(args, path)

    return dict(
        path=path,
        hostname=hostname,
        frequency=args.frequency.value,
        category=args.category,
        time_created=datetime.utcnow().timestamp(),
        time_modified=None,
        play_count=0,
    )


def tabs_add():
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
