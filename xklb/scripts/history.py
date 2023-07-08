import argparse

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
        help=f"One of: {', '.join(consts.frequency)} (default: %(default)s)",
    )

    parser.add_argument("--print", "-p", default="p", const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a column when printing")
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue")
    parser.add_argument("--played", "--opened", action="store_true")
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
        help=f"One of: {', '.join(consts.time_facets)} (default: %(default)s)",
    )

    args = parser.parse_args()

    args.facet = utils.partial_startswith(args.facet, consts.time_facets)
    args.frequency = utils.partial_startswith(args.frequency, consts.frequency)

    if args.db:
        args.database = args.db
    args.db = db.connect(args)

    args.action = consts.SC.history
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def recent_media(args, time_column):
    m_columns = db.columns(args, "media")
    query = f"""
    SELECT
        path
        {', title' if 'title' in m_columns else ''}
        {', duration' if 'duration' in m_columns else ''}
        {', subtitle_count' if 'subtitle_count' in m_columns else ''}
        , {time_column}
    FROM media m
    {'JOIN history h on h.media_id = m.id' if args.played else ''}
    WHERE 1=1
      AND coalesce({time_column}, 0)>0
    {'' if time_column =="time_deleted" else "AND COALESCE(time_deleted, 0)=0"}
    ORDER BY {time_column} desc
    LIMIT {args.limit or 5}
    """
    return list(args.db.query(query))


def history() -> None:
    args = parse_args()
    m_columns = args.db["media"].columns_dict
    create(args)

    WATCHED = ["watched", "listened", "seen", "heard"]
    WATCHING = ["watching", "listening"]
    if args.facet in WATCHED + WATCHING:
        args.played = True

    history_fn = player.historical_usage_items
    if args.played:
        history_fn = player.historical_usage

    if args.facet in WATCHING:
        print(args.facet.title() + ":")
        tbl = history_fn(args, args.frequency, "time_played", "and coalesce(play_count, 0)=0")
        player.media_printer(args, tbl)
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
                JOIN history h on h.media_id = m.id
                WHERE coalesce(time_deleted, 0) = 0
                GROUP BY m.id, m.path
            )
            SELECT *
            FROM m
            WHERE 1=1
                and playhead > 60
                and coalesce(play_count, 0) = 0
            ORDER BY time_last_played desc, playhead desc
            LIMIT {args.limit or 5}
        """
        tbl = list(args.db.query(query))
        player.media_printer(args, tbl)

    elif args.facet in WATCHED:
        print(args.facet.title() + ":")
        tbl = history_fn(args, args.frequency, "time_played", "and coalesce(play_count, 0)>0")
        player.media_printer(args, tbl)
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
                JOIN history h on h.media_id = m.id
                WHERE coalesce(time_deleted, 0) = 0
                GROUP BY m.id, m.path
            )
            SELECT *
            FROM m
            WHERE play_count > 0
            ORDER BY time_last_played desc, path
            LIMIT {args.limit or 5}
        """
        tbl = list(args.db.query(query))
        player.media_printer(args, tbl)

    else:
        print(f"{args.facet.title()} media:")
        tbl = history_fn(args, args.frequency, f"time_{args.facet}")
        player.media_printer(args, tbl)
        tbl = recent_media(args, f"time_{args.facet}")
        player.media_printer(args, tbl)


if __name__ == "__main__":
    history()
