import argparse

from xklb import media_printer, usage
from xklb.mediadb import db_history
from xklb.mediadb.db_history import create
from xklb.utils import arggroups, consts, db_utils, objects, sql_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        "library history",
        usage=usage.history,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    arggroups.sql_fs(parser)
    arggroups.sql_media(parser)

    parser.add_argument("--hide-deleted", action="store_true")
    arggroups.history(parser)
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_intermixed_args()

    args.db = db_utils.connect(args)

    args.action = consts.SC.history
    log.info(objects.dict_filter_bool(args.__dict__))

    args.filter_bindings = {}

    return args


def process_search(args, m_columns):
    args.table = "media"
    if args.db["media"].detect_fts():
        if args.include:
            args.table, search_bindings = db_utils.fts_search_sql(
                "media",
                fts_table=args.db["media"].detect_fts(),
                include=args.include,
                exclude=args.exclude,
            )
            args.filter_bindings = search_bindings
        elif args.exclude:
            db_utils.construct_search_bindings(
                args,
                [f"m.{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
            )
    else:
        db_utils.construct_search_bindings(
            args,
            [f"m.{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
        )


def historical_media(args, m_columns):
    process_search(args, m_columns)
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
            FROM {args.table} m
            JOIN history h on h.media_id = m.id
            WHERE 1=1
            {sql_utils.filter_time_played(args)}
            {'AND COALESCE(time_deleted, 0)=0' if args.hide_deleted else ""}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        WHERE 1=1
            {" ".join([" and " + w for w in args.where])}
            {sql_utils.filter_play_count(args)}
        ORDER BY time_last_played desc {', path' if args.completed else ', playhead desc' }
        LIMIT {args.limit or 5}
    """
    tbl = list(args.db.query(query, args.filter_bindings))
    return tbl


def remove_duplicate_data(tbl):
    for d in tbl:
        if d.get("play_count", 0) <= 1:
            del d["time_first_played"]


def history() -> None:
    args = parse_args()
    m_columns = args.db["media"].columns_dict
    create(args)

    if args.completed:
        print("Completed:")
    elif args.in_progress:
        print("In progress:")
    else:
        print("History:")

    tbl = historical_media(args, m_columns)
    remove_duplicate_data(tbl)

    if args.delete_rows:
        with args.db.conn:
            args.db.conn.execute("DELETE from history WHERE media_id NOT IN (SELECT id FROM media)")
        db_history.remove(args, paths=[d["path"] for d in tbl])

    args.delete_rows = False
    media_printer.media_printer(args, tbl)


if __name__ == "__main__":
    history()
