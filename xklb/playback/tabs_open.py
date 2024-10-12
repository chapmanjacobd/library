import argparse, math

from xklb import usage
from xklb.mediadb import db_history
from xklb.playback import media_printer
from xklb.utils import arggroups, argparse_utils, consts, db_utils, devices, processes
from xklb.utils.log_utils import log
from xklb.utils.sqlgroups import construct_tabs_query


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.tabs_open)

    arggroups.sql_fs(parser)
    parser.add_argument("--max-same-domain", type=int, help="Limit to N tabs per domain")
    parser.add_argument("--browser", nargs="?", const="default")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*")

    parser.set_defaults(fts=False)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    return args


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


def play(args, media):
    links = [m["path"] for m in media]
    devices.browse(args.browser or "default", links)
    db_history.add(args, links, time_played=consts.today_stamp(), mark_done=True)


def tabs_open() -> None:
    args = parse_args()
    db_history.create(args)

    query, bindings = construct_tabs_query(args)

    if args.print or args.delete_rows or args.mark_deleted or args.mark_watched:
        media_printer.printer(args, query, bindings)
        return

    media = list(args.db.query(query, bindings))
    if not media:
        processes.no_media_found()

    m_columns = db_utils.columns(args, "media")
    counts = args.db.execute(
        f"""
        SELECT
            frequency, count(*)
        FROM media
        WHERE 1=1
            {"and COALESCE(time_deleted,0)=0" if 'time_deleted' in m_columns else ''}
        GROUP BY 1
    """
    ).fetchall()
    media = frequency_filter(counts, media)

    play(args, media)
