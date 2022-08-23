import argparse
from time import sleep

import pandas as pd

from xklb.db import sqlite_con
from xklb.tabs_extract import Frequency
from xklb.utils import SC, cmd, filter_None, flatten, log
from xklb.utils_player import generic_player, mark_media_watched, override_sort, printer

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
            WHEN frequency = 'daily' THEN cast(STRFTIME('%s', datetime( time_played, 'unixepoch', '+1 Day' )) as int)
            WHEN frequency = 'weekly' THEN cast(STRFTIME('%s', datetime( time_played, 'unixepoch', '+7 Days' )) as int)
            WHEN frequency = 'monthly' THEN cast(STRFTIME('%s', datetime( time_played, 'unixepoch', '+1 Month' )) as int)
            WHEN frequency = 'quarterly' THEN cast(STRFTIME('%s', datetime( time_played, 'unixepoch', '+3 Months' )) as int)
            WHEN frequency = 'yearly' THEN cast(STRFTIME('%s', datetime( time_played, 'unixepoch', '+1 Year' )) as int)
        END time_valid
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM media
    WHERE 1=1
        {args.sql_filter}
        {"and date(time_valid, 'unixepoch') < date()" if not args.print else ''}
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


def frequency_filter(args, media: pd.DataFrame):
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

    media = frequency_filter(args, media)

    play(args, media)


def parse_args(action, default_db, default_chromecast=""):
    parser = argparse.ArgumentParser(prog="lb tabs", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "database",
        nargs="?",
        default=default_db,
        help="Database file. If not specified a generic name will be used: audio.db, video.db, fs.db, etc",
    )

    parser.add_argument(
        "--sort",
        "-u",
        nargs="+",
        help="""Sort media with SQL expressions
-u duration means shortest media first
-u duration desc means longest media first

You can use any sqlite ORDER BY expressions, for example:
-u subtitle_count > 0
means play everything that has a subtitle first
""",
    )
    parser.add_argument(
        "--where",
        "-w",
        nargs="+",
        action="extend",
        default=[],
        help="""Constrain media with SQL expressions
You can use any sqlite WHERE expressions, for example:
-w attachment_count > 0  means only media with attachments
-w language = 'eng'  means only media which has some English language tag -- this could be audio or subtitle""",
    )
    parser.add_argument(
        "--include",
        "-s",
        "--search",
        nargs="+",
        action="extend",
        default=[],
        help="""Constrain media with via search
-s toy story will match '/folder/toy/something/story.mp3'
-s 'toy  story' will match more strictly '/folder/toy story.mp3'
Double spaces means one space
""",
    )
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help="--include but opposite")

    parser.add_argument(
        "--print",
        "-p",
        default=False,
        const="p",
        nargs="?",
        help="""Print instead of play
-p   means print in a table
-p a means print an aggregate report
-p f means print only filenames -- useful for piping to other utilities like xargs or GNU Parallel""",
    )
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a non-standard column when printing")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help="Set play queue size")
    parser.add_argument("--skip", "-S", help="Offset from the top of an ordered query; wt -S10 to skip ten videos")

    parser.add_argument("--db", "-db")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db

    if args.sort:
        args.sort = " ".join(args.sort)
        args.sort = override_sort(args.sort)

    if args.cols:
        args.cols = list(flatten([s.split(",") for s in args.cols]))

    log.info(filter_None(args.__dict__))

    return args


def tabs():
    args = parse_args(SC.tabs, "tabs.db")
    process_tabs_actions(args, construct_tabs_query)
