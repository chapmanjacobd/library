import argparse, json
from copy import deepcopy
from typing import Tuple

from tabulate import tabulate

from xklb import consts, db, usage, utils
from xklb.player import delete_playlists
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        "library playlists",
        usage.playlists,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--aggregate", "-a", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", "-j", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--errors", "-errors", "--error", action="store_true", help="Show only rows with errors")
    parser.add_argument("--delete", "--remove", "--erase", "--rm", "-rm", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)

    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    args = parser.parse_args()
    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    args.action = consts.SC.stats
    return args


def construct_query(args) -> Tuple[str, dict]:
    utils.ensure_playlists_exists(args)
    pl_columns = args.db["playlists"].columns_dict
    args.filter_sql = []
    args.filter_bindings = {}

    args.filter_sql.extend([" and " + w for w in args.where])

    args.table = "playlists"
    if args.db["playlists"].detect_fts():
        if args.include:
            args.table = db.fts_flexible_search(args)
        elif args.exclude:
            db.construct_search_bindings(args, pl_columns)
    else:
        db.construct_search_bindings(args, pl_columns)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    query = f"""SELECT
        *
    FROM {args.table}
    WHERE 1=1
        and COALESCE(time_deleted,0) = 0
        {" ".join(args.filter_sql)}
        and (category is null or category != '{consts.BLOCK_THE_CHANNEL}')
    ORDER BY 1=1
        {', ' + args.sort if args.sort else ''}
        , path
        , random()
    {LIMIT}
    """

    return query, args.filter_bindings


def printer(args, query, bindings) -> None:
    media = list(args.db.query(query, bindings))
    media = utils.list_dict_filter_bool(media)
    if not media:
        utils.no_media_found()

    tbl = deepcopy(media)
    utils.col_naturaldate(tbl, "avg_time_since_download")
    utils.col_naturalsize(tbl, "size")
    utils.col_duration(tbl, "duration")
    utils.col_duration(tbl, "avg_playlist_duration")

    if args.print and "f" in args.print:
        utils.pipe_print("\n".join([d["path"] for d in media]))
        return
    elif args.json or consts.TERMINAL_SIZE.columns < 80:
        print(json.dumps(tbl, indent=3))
    else:
        tbl = utils.col_resize(tbl, "path", 30)
        tbl = utils.col_resize(tbl, "title", 20)
        tbl = utils.col_resize(tbl, "uploader_url")

        tbl = utils.list_dict_filter_bool(tbl)

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))

    print(f"{len(media)} playlists" if len(media) > 1 else "1 playlist")
    duration = sum(m.get("duration") or 0 for m in media)
    if duration > 0:
        duration = utils.human_time(duration)
        if not args.aggregate:
            print("Total duration:", duration)


def playlists() -> None:
    args = parse_args()

    if args.delete:
        return delete_playlists(args, args.delete)

    pl_columns = args.db["playlists"].columns_dict
    m_columns = args.db["media"].columns_dict
    query, bindings = construct_query(args)

    if "playlist_path" in m_columns:
        query = f"""
        select
            coalesce(p.path, "Playlist-less media") path
            {', p.ie_key' if 'ie_key' in pl_columns else ''}
            {', p.title' if 'title' in pl_columns else ''}
            {', p.time_deleted' if 'time_deleted' in pl_columns else ''}
            {', count(*) FILTER(WHERE play_count>0) play_count' if 'play_count' in m_columns else ''}
            {', sum(m.duration) duration' if 'duration' in m_columns else ''}
            {', sum(m.size) size' if 'size' in m_columns else ''}
            , count(*) count
        from media m
        left join ({query}) p on (p.path = m.playlist_path {"and p.ie_key = m.ie_key and m.ie_key != 'Local'" if 'ie_key' in m_columns else ''})
        group by coalesce(p.path, "Playlist-less media")
        order by count, p.category nulls last, p.path
        """

    if args.aggregate:
        query = f"""
        select
            'Aggregate of playlists' path
            {', count(*) FILTER(WHERE time_deleted>0) deleted_count' if 'time_deleted' in query else ''}
            {', sum(play_count) play_count' if 'play_count' in query else ''}
            {', sum(duration) duration' if 'duration' in query else ''}
            {', avg(duration) avg_playlist_duration' if 'duration' in query else ''}
            {', sum(size) size' if 'size' in query else ''}
            , count(*) playlists_count
            {', sum(count) videos_count' if 'count' in query else ''}
        from ({query})
        """

    printer(args, query, bindings)
    return None
