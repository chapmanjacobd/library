import argparse

from tabulate import tabulate

from xklb import consts, db, player, usage, utils
from xklb.history import create
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        "library history",
        usage=usage.history,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--frequency",
        "--freqency",
        "-f",
        metavar="frequency",
        default="monthly",
        const="monthly",
        type=str.lower,
        nargs="?",
        help="One of: %(choices)s (default: %(default)s)",
    )

    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue")

    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    parser.add_argument(
        "facet",
        metavar="facet",
        type=str.lower,
        default="watching",
        const="watching",
        nargs="?",
        help="One of: %(choices)s (default: %(default)s)",
    )

    args = parser.parse_args()

    args.facet = utils.partial_startswith(args.facet, consts.time_facets)
    args.frequency = utils.partial_startswith(args.frequency, consts.frequency)

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def print_history(tbl):
    utils.col_duration(tbl, "duration_sum")
    utils.col_duration(tbl, "duration_avg")
    utils.col_naturalsize(tbl, "size_sum")
    utils.col_naturalsize(tbl, "size_avg")
    tbl = utils.list_dict_filter_bool(tbl)
    print(tabulate(tbl, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False))


def print_recent(tbl, time_column=None):
    utils.col_duration(tbl, "duration")
    utils.col_duration(tbl, "playhead")
    if time_column:
        utils.col_naturaltime(tbl, time_column)
    tbl = [{"title_path": "\n".join(utils.concat(d["title"], d["path"])), **d} for d in tbl]
    tbl = [{k: v for k, v in d.items() if k not in ("title", "path")} for d in tbl]

    tbl = utils.col_resize(tbl, "title_path", 40)
    tbl = utils.col_resize(tbl, "duration", 5)
    tbl = utils.col_resize(tbl, "playhead", 5)
    tbl = utils.list_dict_filter_bool(tbl)
    print(tabulate(tbl, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False))


def recent_media(args, time_column):
    m_columns = db.columns(args, "media")
    query = f"""
    SELECT
        path
        {', title' if 'title' in m_columns else ''}
        {', duration' if 'duration' in m_columns else ''}
        {', subtitle_count' if 'subtitle_count' in m_columns else ''}
        , {time_column}
    FROM media
    WHERE coalesce({time_column}, 0)>0
    ORDER BY {time_column} desc
    LIMIT {args.limit or 5}
    """
    return list(args.db.query(query))


def history() -> None:
    args = parse_args()
    create(args)

    m_columns = args.db["media"].columns_dict

    if args.facet.startswith("watching"):
        print("Partially watched:")
        tbl = player.historical_usage(args, args.frequency, "time_played", "and coalesce(play_count, 0)=0")
        print_history(tbl)
        query = f"""WITH m as (
                SELECT
                    SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                    , MIN(h.time_played) time_first_played
                    , MAX(h.time_played) time_last_played
                    , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                    , path
                    {', title' if 'title' in m_columns else ''}
                    {', duration' if 'duration' in m_columns else ''}
                    {', subtitle_count' if 'subtitle_count' in m_columns else ''}
                FROM media m
                LEFT JOIN history h on h.media_id = m.id
                WHERE coalesce(time_deleted, 0) = 0
                GROUP BY m.id, m.path
            )
            SELECT *
            FROM m
            WHERE 1=1
                and coalesce(playhead, 0) > 60
                and coalesce(play_count, 0) = 0
            ORDER BY time_last_played desc, playhead desc
            LIMIT {args.limit or 5}
        """
        tbl = list(args.db.query(query))
        print_recent(tbl, "time_last_played")

    elif args.facet.startswith("watched"):
        print("Finished watching:")
        tbl = player.historical_usage(args, args.frequency, "time_played", "and coalesce(play_count, 0)>0")
        print_history(tbl)
        query = f"""WITH m as (
                SELECT
                    SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                    , MIN(h.time_played) time_first_played
                    , MAX(h.time_played) time_last_played
                    , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                    , path
                    {', title' if 'title' in m_columns else ''}
                    {', duration' if 'duration' in m_columns else ''}
                    {', subtitle_count' if 'subtitle_count' in m_columns else ''}
                FROM media m
                LEFT JOIN history h on h.media_id = m.id
                GROUP BY m.id, m.path
            )
            SELECT *
            FROM m
            WHERE coalesce(play_count, 0)>0
            ORDER BY time_last_played desc, path
            LIMIT {args.limit or 5}
        """
        tbl = list(args.db.query(query))
        print_recent(tbl, "time_last_played")

    else:
        print(f"{args.facet.title()} media:")
        tbl = player.historical_usage(args, args.frequency, f"time_{args.facet}")
        print_history(tbl)
        tbl = recent_media(args, f"time_{args.facet}")
        print_recent(tbl, f"time_{args.facet}")


if __name__ == "__main__":
    history()
