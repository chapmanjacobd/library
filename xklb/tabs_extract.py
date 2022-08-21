import argparse
import enum
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


def reddit_frequency(frequency: Frequency):
    mapper = {
        Frequency.Daily: "day",
        Frequency.Weekly: "week",
        Frequency.Monthly: "month",
        Frequency.Quarterly: "year",
        Frequency.Yearly: "year",
    }

    return mapper.get(frequency, "month")


def extract_url_metadata(args, path):
    hostname = urlparse(path).hostname or ""
    if args.sanitize:
        if "reddit" in hostname:
            path = urljoin(path, "?sort=top&t=" + reddit_frequency(args.frequency))

    return dict(
        path=path,
        hostname=hostname,
        frequency=args.frequency.value,
        category=args.category,
        time_created=datetime.utcnow(),
        time_modified=None,
        play_count=0
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


"""
open browser
print

by frequency (math.min(args.limit, freq_limit))
by number -L

import pandas as pd
quarter = pd.Timestamp(dt.date(2016, 2, 29)).quarter

(x.month-1)//3 +1 quarter

people can read ahead and if they read everything then running tb won't do anything until the minimum time of the set frequency

example frequency that could be used:

    -q daily
    -q weekly (spaced evenly throughout the week if less than 7 links in the category)
    -q monthly (spaced evenly throughout the month if less than 30 links in the category)
    -q quarterly (spaced evenly throughout the month if less than 90 links in the category)
    -q yearly (spaced evenly throughout the year if less than 365 links in the category)

if 14 tabs, two URLs are opened per day of the week.

1 cron daily

categoryless mode: ignore categories when determining sequencing--only frequency is used

cron is responsible for running python. `lb tabs` is merely a way to organize tabs into different categories--but you could easily do this with files as well.
"""


def tabs_import():
    args = parse_args()

    args.tabs
