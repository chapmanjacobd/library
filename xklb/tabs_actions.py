from time import sleep

import pandas as pd

from xklb.db import sqlite_con
from xklb.fs_actions import parse_args
from xklb.tabs_extract import Frequency
from xklb.utils import SC, cmd
from xklb.utils_player import generic_player, mark_media_watched, printer

tabs_include_string = (
    lambda x: f"""and (
    path like :include{x}
    OR category like :include{x}
    OR frequency like :include{x}
)"""
)

tabs_exclude_string = (
    lambda x: f"""and (
    path not like :exclude{x}
    AND category not like :exclude{x}
    AND frequency not like :exclude{x}
)"""
)


def construct_tabs_query(args):
    cf = []
    bindings = {}

    cf.extend([" and " + w for w in args.where])

    for idx, inc in enumerate(args.include):
        cf.append(tabs_include_string(idx))
        bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        cf.append(tabs_exclude_string(idx))
        bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"

    args.sql_filter = " ".join(cf)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""SELECT path
        , frequency
        , CASE
            WHEN frequency = 'daily' THEN UNIXEPOCH(datetime( time_played, 'unixepoch', '+1 Day' ))
            WHEN frequency = 'weekly' THEN UNIXEPOCH(datetime( time_played, 'unixepoch', '+1 Week' ))
            WHEN frequency = 'monthly' THEN UNIXEPOCH(datetime( time_played, 'unixepoch', '+1 Month' ))
            WHEN frequency = 'quarterly' THEN UNIXEPOCH(datetime( time_played, 'unixepoch', '+3 Months' ))
            WHEN frequency = 'yearly' THEN UNIXEPOCH(datetime( time_played, 'unixepoch', '+1 Year' ))
        END time_valid
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM media
    WHERE 1=1
        {args.sql_filter}
        {"and (time_played is null or date(time_valid, 'unixepoch') < date(unixepoch(), 'unixepoch'))" if not args.print else ''}
    ORDER BY 1=1
        {',' + args.sort if args.sort else ''}
        , play_count
        , frequency = 'daily' desc
        , frequency = 'weekly' desc
        , frequency = 'monthly' desc
        , frequency = 'quarterly' desc
        , frequency = 'yearly' desc
        {', path' if args.print else ''}
        , ROW_NUMBER() OVER ( PARTITION BY category ) -- prefer to spread categories over time
        , random()
    {LIMIT} {OFFSET}
    """

    return query, bindings


def play(args, media: pd.DataFrame):
    for m in media.to_records():
        media_file = m["path"]

        cmd(*generic_player(args), media_file, strict=False)
        mark_media_watched(args, media_file)

        if len(media) > 10:
            sleep(0.3)


def frenquency_filter(args, media: pd.DataFrame):
    mapper = {
        Frequency.Daily: 1,
        Frequency.Weekly: 7,
        Frequency.Monthly: 30,
        Frequency.Quarterly: 91,
        Frequency.Yearly: 365,
    }
    counts = args.con.execute("select frequency, count(*) from media group by 1").fetchall()
    for freq, freq_count in counts:
        num_days = mapper.get(freq, 365)
        num_tabs = max(1, freq_count // num_days)
        media[media.frequency == freq] = media[media.frequency == freq].head(num_tabs)
        media.dropna(inplace=True)

    return media


def process_tabs_actions(args, construct_query):
    args.con = sqlite_con(args.database)
    query, bindings = construct_query(args)

    if args.print:
        return printer(args, query, bindings)

    media = pd.DataFrame([dict(r) for r in args.con.execute(query, bindings).fetchall()])
    if len(media) == 0:
        print("No media found")
        exit(2)

    media = frenquency_filter(args, media)

    play(args, media)


def tabs():
    args = parse_args(SC.tabs, "tabs.db")
    process_tabs_actions(args, construct_tabs_query)
