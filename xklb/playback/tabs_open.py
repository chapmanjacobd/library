import argparse, math, webbrowser
from time import sleep

from xklb import media_printer, usage
from xklb.mediadb import db_history
from xklb.utils import arggroups, argparse_utils, consts, processes
from xklb.utils.log_utils import log
from xklb.utils.sqlgroups import construct_tabs_query


def parse_args(action) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(
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
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    return args


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
