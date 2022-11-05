import argparse, json, operator
from copy import deepcopy
from typing import Tuple

from tabulate import tabulate

from xklb import consts, db, dl_extract, utils
from xklb.play_actions import construct_search_bindings
from xklb.player import delete_playlists
from xklb.utils import human_time, log


def parse_args(prog, usage):
    parser = argparse.ArgumentParser(prog, usage)
    parser.add_argument("--fields", "-f", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--aggregate", "-a", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", "-j", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--delete", "--remove", "--erase", "--rm", "-rm", nargs="+", help=argparse.SUPPRESS)
    if "dlstatus" in prog:
        parser.add_argument(
            "--retry-delay",
            "-r",
            default="14 days",
            help="Must be specified in SQLITE Modifiers format: N hours, days, months, or years",
        )

    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="video.db")
    args = parser.parse_args()
    return args


def construct_query(args) -> Tuple[str, dict]:
    utils.ensure_playlists_exists(args)
    pl_columns = args.db["playlists"].columns_dict
    cf = []
    bindings = {}

    cf.extend([" and " + w for w in args.where])

    args.table = "playlists"
    if args.db["playlists"].detect_fts():
        if args.include:
            args.table = db.fts_search(args, bindings)
        elif args.exclude:
            construct_search_bindings(args, cf, bindings, pl_columns)
    else:
        construct_search_bindings(args, cf, bindings, pl_columns)

    args.sql_filter = " ".join(cf)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    query = f"""SELECT
        *
    FROM {args.table}
    WHERE 1=1
        and time_deleted=0
        {args.sql_filter}
        and (category is null or category != '{consts.BLOCK_THE_CHANNEL}')
    ORDER BY 1=1
        {', ' + args.sort if args.sort else ''}
        , path
        , random()
    {LIMIT}
    """

    return query, bindings


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

    if args.fields:
        print("\n".join(list(map(operator.itemgetter("path"), media))))
        return
    elif args.json or consts.TERMINAL_SIZE.columns < 80:
        print(json.dumps(tbl, indent=3))
    else:
        tbl = utils.col_resize(tbl, "path", 30)
        tbl = utils.col_resize(tbl, "title", 20)
        tbl = utils.col_resize(tbl, "uploader_url")

        tbl = utils.list_dict_filter_bool(tbl, keep_0=False)

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))

    print(f"{len(media)} playlists" if len(media) >= 2 else "1 playlist")
    duration = sum(map(lambda m: m.get("duration") or 0, media))
    if duration > 0:
        duration = human_time(duration)
        if not args.aggregate:
            print("Total duration:", duration)


def playlists() -> None:
    args = parse_args(
        prog="library playlists",
        usage="""library playlists [database] [--aggregate] [--fields] [--json] [--delete ...]

    List of Playlists

        library playlists
        ╒══════════╤════════════════════╤══════════════════════════════════════════════════════════════════════════╕
        │ ie_key   │ title              │ path                                                                     │
        ╞══════════╪════════════════════╪══════════════════════════════════════════════════════════════════════════╡
        │ Youtube  │ Highlights of Life │ https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n │
        ╘══════════╧════════════════════╧══════════════════════════════════════════════════════════════════════════╛

    Aggregate Report of Videos in each Playlist

        library playlists -p a
        ╒══════════╤════════════════════╤══════════════════════════════════════════════════════════════════════════╤═══════════════╤═════════╕
        │ ie_key   │ title              │ path                                                                     │ duration      │   count │
        ╞══════════╪════════════════════╪══════════════════════════════════════════════════════════════════════════╪═══════════════╪═════════╡
        │ Youtube  │ Highlights of Life │ https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n │ 53.28 minutes │      15 │
        ╘══════════╧════════════════════╧══════════════════════════════════════════════════════════════════════════╧═══════════════╧═════════╛
        1 playlist
        Total duration: 53.28 minutes

    Print only playlist urls:
        Useful for piping to other utilities like xargs or GNU Parallel.
        library playlists -p f
        https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n

    Remove a playlist/channel and all linked videos:
        library playlists --remove https://vimeo.com/canal180

    """,
    )

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

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
            {', sum(media.duration) duration' if 'duration' in m_columns else ''}
            {', sum(media.size) size' if 'size' in m_columns else ''}
            , count(*) count
        from media
        left join ({query}) p on (p.path = media.playlist_path {"and p.ie_key = media.ie_key and media.ie_key != 'Local'" if 'ie_key' in m_columns else ''})
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


def dlstatus() -> None:
    args = parse_args(
        prog="library dlstatus",
        usage="""library dlstatus [database]

    Print download queue groups

        library dlstatus video.db
        ╒═════════════════════╤═════════════╤══════════════════╤════════════════════╤══════════╕
        │ category            │ ie_key      │ duration         │   never_downloaded │   errors │
        ╞═════════════════════╪═════════════╪══════════════════╪════════════════════╪══════════╡
        │ 71_Mealtime_Videos  │ Youtube     │ 3 hours and 2.07 │                 76 │        0 │
        │                     │             │ minutes          │                    │          │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ 75_MovieQueue       │ Dailymotion │                  │                 53 │        0 │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ 75_MovieQueue       │ Youtube     │ 1 day, 18 hours  │                 30 │        0 │
        │                     │             │ and 6 minutes    │                    │          │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Dailymotion         │ Dailymotion │                  │                186 │      198 │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Uncategorized       │ Youtube     │ 1 hour and 52.18 │                  1 │        0 │
        │                     │             │ minutes          │                    │          │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Vimeo               │ Vimeo       │                  │                253 │       49 │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Youtube             │ Youtube     │ 2 years, 4       │              51676 │      197 │
        │                     │             │ months, 15 days  │                    │          │
        │                     │             │ and 6 hours      │                    │          │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Playlist-less media │ Youtube     │ 4 months, 23     │               2686 │        7 │
        │                     │             │ days, 19 hours   │                    │          │
        │                     │             │ and 33 minutes   │                    │          │
        ╘═════════════════════╧═════════════╧══════════════════╧════════════════════╧══════════╛
    """,
    )

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    if args.delete:
        return delete_playlists(args, args.delete)

    query, bindings = dl_extract.construct_query(args)
    query = f"""select
        coalesce(category, "Playlist-less media") category
        {', ie_key' if 'media.ie_key' in query else ''}
        {', sum(duration) duration' if 'duration' in query else ''}
        {', count(*) FILTER(WHERE time_modified=0) never_downloaded' if 'time_modified' in query else ''}
        {', count(*) FILTER(WHERE time_modified>0 AND error IS NOT NULL) errors' if 'error' in query else ''}
        {', group_concat(distinct error) error_descriptions' if 'error' in query and args.verbose >= 1 else ''}
    from ({query})
    where 1=1
        and time_downloaded=0
        and time_deleted=0
    group by category{', ie_key' if 'media.ie_key' in query else ''}
    order by category nulls last"""

    printer(args, query, bindings)
