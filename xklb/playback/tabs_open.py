import argparse, math, webbrowser
from pathlib import Path
from time import sleep

from xklb import media_printer, usage
from xklb.mediadb import db_history
from xklb.utils import arg_utils, arggroups, consts, db_utils, iterables, objects, processes
from xklb.utils.log_utils import log


def parse_args(action) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library tabs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        usage=usage.tabs_open,
    )
    arggroups.sql_fs(parser)
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = action

    args.include += args.search
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if args.sort:
        args.sort = [arg_utils.override_sort(s) for s in args.sort]
        args.sort = " ".join(args.sort)

    if args.cols:
        args.cols = list(iterables.flatten([s.split(",") for s in args.cols]))

    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def tabs_include_sql(x) -> str:
    return f"""and (
    path like :include{x}
    OR category like :include{x}
    OR frequency like :include{x}
)"""


def tabs_exclude_sql(x) -> str:
    return f"""and (
    path not like :exclude{x}
    AND category not like :exclude{x}
    AND frequency not like :exclude{x}
)"""


def construct_tabs_query(args) -> tuple[str, dict]:
    args.filter_sql = []
    args.filter_bindings = {}

    args.filter_sql.extend([" and " + w for w in args.where])

    for idx, inc in enumerate(args.include):
        args.filter_sql.append(tabs_include_sql(idx))
        if args.exact:
            args.filter_bindings[f"include{idx}"] = inc
        else:
            args.filter_bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        args.filter_sql.append(tabs_exclude_sql(idx))
        if args.exact:
            args.filter_bindings[f"exclude{idx}"] = exc
        else:
            args.filter_bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.offset}" if args.offset else ""

    query = f"""WITH m as (
            SELECT
                path
                , frequency
                , COALESCE(MAX(h.time_played), 0) time_last_played
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , time_deleted
                , hostname
                , category
            FROM media
            LEFT JOIN history h on h.media_id = media.id
            WHERE COALESCE(time_deleted, 0)=0
            GROUP BY media.id
        )
        SELECT path
        , frequency
        {", time_last_played" if args.print else ''}
        , CASE
            WHEN frequency = 'daily' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Day', '-5 minutes' )) as int)
            WHEN frequency = 'weekly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+7 Days', '-5 minutes' )) as int)
            WHEN frequency = 'monthly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Month', '-5 minutes' )) as int)
            WHEN frequency = 'quarterly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+3 Months', '-5 minutes' )) as int)
            WHEN frequency = 'yearly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Year', '-5 minutes' )) as int)
        END time_valid
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM m
    WHERE 1=1
        {" ".join(args.filter_sql)}
        {f"and time_valid < {consts.today_stamp()}" if not args.print else ''}
    ORDER BY 1=1
        {', ' + args.sort if args.sort else ''}
        {', time_last_played, time_valid, path' if args.print else ''}
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

    return query, args.filter_bindings


def play(args, m: dict) -> None:
    media_file = m["path"]

    webbrowser.open(media_file, 2, autoraise=False)
    db_history.add(args, [media_file], time_played=consts.today_stamp(), mark_done=True)


def frequency_filter(counts, media: list[dict]) -> list[dict]:
    mapper = {
        "daily": 1,
        "weekly": 7,
        "monthly": 30,
        "quarterly": 91,
        "yearly": 365,
    }
    filtered_media = []
    for freq, freq_count in counts:
        num_days = mapper.get(freq, 365)
        num_tabs = max(1, math.ceil(freq_count / num_days))
        log.debug(f"freq_count {freq_count} / num_days {num_days} = num_tabs {num_tabs}")

        filtered_media.extend([m for m in media if m["frequency"] == freq][:num_tabs])

    return filtered_media


def tabs_open() -> None:
    args = parse_args(consts.SC.tabs_open)
    db_history.create(args)

    query, bindings = construct_tabs_query(args)

    if args.print or args.delete_rows or args.mark_deleted or args.mark_watched:
        media_printer.printer(args, query, bindings)
        return

    media = list(args.db.query(query, bindings))
    if not media:
        processes.no_media_found()

    counts = args.db.execute("select frequency, count(*) from media group by 1").fetchall()
    media = frequency_filter(counts, media)

    for m in media:
        play(args, m)
        if len(media) >= consts.MANY_LINKS:
            sleep(0.3)
