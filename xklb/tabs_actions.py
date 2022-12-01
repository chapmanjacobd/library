import argparse
from time import sleep
from typing import Dict, List, Tuple

from xklb import db, utils
from xklb.consts import SC
from xklb.player import generic_player, mark_media_watched, override_sort, printer
from xklb.tabs_extract import Frequency
from xklb.utils import cmd, flatten, log

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


def construct_tabs_query(args) -> Tuple[str, dict]:
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
        {"and time_valid < cast(STRFTIME('%s', datetime()) as int)" if not args.print else ''}
    ORDER BY 1=1
        {', ' + args.sort if args.sort else ''}
        {', time_played, time_valid, path' if args.print else ''}
        , play_count
        , frequency = 'daily' desc
        , frequency = 'weekly' desc
        , frequency = 'monthly' desc
        , frequency = 'quarterly' desc
        , frequency = 'yearly' desc
        , ROW_NUMBER() OVER ( PARTITION BY
            play_count
            , frequency
            , hostname
            , category
        ) -- prefer to spread hostname, category over time
        , random()
    {LIMIT} {OFFSET}
    """

    return query, bindings


def play(args, m: Dict) -> None:
    media_file = m["path"]

    cmd(*generic_player(args), media_file, strict=False)
    mark_media_watched(args, media_file)


def frequency_filter(args, media: List[Dict]) -> List[dict]:
    mapper = {
        Frequency.Daily.value: 1,
        Frequency.Weekly.value: 7,
        Frequency.Monthly.value: 30,
        Frequency.Quarterly.value: 91,
        Frequency.Yearly.value: 365,
    }
    counts = args.db.execute("select frequency, count(*) from media group by 1").fetchall()
    filtered_media = []
    for freq, freq_count in counts:
        num_days = mapper.get(freq, 365)
        num_tabs = max(1, freq_count // num_days)
        log.debug(f"freq_count {freq_count} // num_days {num_days} = num_tabs {num_tabs}")

        t = []
        for m in media:
            if m["frequency"] == freq:
                t.append(m)

        filtered_media.extend(t[:num_tabs])

    return filtered_media


def process_tabs_actions(args) -> None:
    query, bindings = construct_tabs_query(args)

    if args.print:
        return printer(args, query, bindings)

    media = list(args.db.query(query, bindings))
    if not media:
        utils.no_media_found()

    media = frequency_filter(args, media)

    for m in media:
        play(args, m)
        if len(media) >= 9:
            sleep(0.3)


def parse_args(action, default_db) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library tabs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        usage="""library tabs [database] [optional args]

    Tabs is meant to run **once per day**. Here is how you would configure it with `crontab`:

        45 9 * * * DISPLAY=:0 library tabs /home/my/tabs.db

    If things aren't working you can use `at` to simulate a similar environment as `cron`

        echo 'fish -c "export DISPLAY=:0 && library tabs /full/path/to/tabs.db"' | at NOW

    You can also invoke tabs manually:

        library tabs -L 1  # open one tab

    Print URLs

        lb-dev tabs -w "frequency='yearly'" -p
        ╒════════════════════════════════════════════════════════════════╤═════════════╤══════════════╕
        │ path                                                           │ frequency   │ time_valid   │
        ╞════════════════════════════════════════════════════════════════╪═════════════╪══════════════╡
        │ https://old.reddit.com/r/Autonomia/top/?sort=top&t=year        │ yearly      │ Dec 31 1970  │
        ├────────────────────────────────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/Cyberpunk/top/?sort=top&t=year        │ yearly      │ Dec 31 1970  │
        ├────────────────────────────────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/ExperiencedDevs/top/?sort=top&t=year  │ yearly      │ Dec 31 1970  │

        ...

        ╘════════════════════════════════════════════════════════════════╧═════════════╧══════════════╛

    View how many yearly tabs you have:

        library tabs -w "frequency='yearly'" -p a
        ╒═══════════╤═════════╕
        │ path      │   count │
        ╞═══════════╪═════════╡
        │ Aggregate │     134 │
        ╘═══════════╧═════════╛

    Delete URLs

        library tb -p -s cyber
        ╒═══════════════════════════════════════╤═════════════╤══════════════╕
        │ path                                  │ frequency   │ time_valid   │
        ╞═══════════════════════════════════════╪═════════════╪══════════════╡
        │ https://old.reddit.com/r/cyberDeck/to │ yearly      │ Dec 31 1970  │
        │ p/?sort=top&t=year                    │             │              │
        ├───────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/Cyberpunk/to │ yearly      │ Aug 29 2023  │
        │ p/?sort=top&t=year                    │             │              │
        ├───────────────────────────────────────┼─────────────┼──────────────┤
        │ https://www.reddit.com/r/cyberDeck/   │ yearly      │ Sep 05 2023  │
        ╘═══════════════════════════════════════╧═════════════╧══════════════╛
        library tb -p -w "path='https://www.reddit.com/r/cyberDeck/'" --delete
        Removed 1 metadata records
        library tb -p -s cyber
        ╒═══════════════════════════════════════╤═════════════╤══════════════╕
        │ path                                  │ frequency   │ time_valid   │
        ╞═══════════════════════════════════════╪═════════════╪══════════════╡
        │ https://old.reddit.com/r/cyberDeck/to │ yearly      │ Dec 31 1970  │
        │ p/?sort=top&t=year                    │             │              │
        ├───────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/Cyberpunk/to │ yearly      │ Aug 29 2023  │
        │ p/?sort=top&t=year                    │             │              │
        ╘═══════════════════════════════════════╧═════════════╧══════════════╛
""",
    )

    parser.add_argument("--sort", "-u", nargs="+")
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[])
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[])
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[])
    parser.add_argument("--print", "-p", default=False, const="p", nargs="?")
    parser.add_argument("--delete", "--remove", "--erase", "--rm", "-rm", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a non-standard column when printing")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue")
    parser.add_argument("--skip", "-S")

    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db")

    parser.add_argument(
        "database",
        nargs="?",
        default=default_db,
        help="Database file. If not specified a generic name will be used: audio.db, video.db, fs.db, etc",
    )
    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db

    if args.sort:
        args.sort = [override_sort(s) for s in args.sort]
        args.sort = " ".join(args.sort)

    if args.cols:
        args.cols = list(flatten([s.split(",") for s in args.cols]))

    if args.delete:
        args.print += "d"

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def tabs() -> None:
    args = parse_args(SC.tabs, "tabs.db")
    process_tabs_actions(args)
