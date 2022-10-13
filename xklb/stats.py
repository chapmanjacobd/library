import argparse, json, operator
from copy import deepcopy
from typing import Tuple

from tabulate import tabulate

from xklb import consts, db, utils
from xklb.play_actions import construct_search_bindings
from xklb.player import delete_playlists
from xklb.utils import human_time, log


def parse_args(prog, usage):
    parser = argparse.ArgumentParser(prog, usage)
    parser.add_argument("--fields", "-f", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--aggregate", "-a", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", "-j", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", default="path", help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--delete", "--remove", "--erase", "--rm", "-rm", nargs="+", help=argparse.SUPPRESS)

    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="video.db")
    args = parser.parse_args()
    return args


def construct_query(args) -> Tuple[str, dict]:
    pl_columns = args.db["playlists"].columns_dict
    cf = []
    bindings = {}

    cf.extend([" and " + w for w in args.where])

    args.table = "playlists"
    if args.db["playlists"].detect_fts():
        if args.include:
            args.table = db.fts_search(args, bindings)
        elif args.exclude:
            construct_search_bindings(args, bindings, cf, pl_columns)
    else:
        construct_search_bindings(args, bindings, cf, pl_columns)

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
        {', ' + args.sort}
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

    if args.fields:
        print("\n".join(list(map(operator.itemgetter("path"), media))))
        return
    elif args.json or consts.TERMINAL_SIZE.columns < 80:
        print(json.dumps(tbl, indent=3))
    else:
        tbl = utils.col_resize(tbl, "path", 40)
        tbl = utils.col_resize(tbl, "uploader_url")

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

    query = f"""
        select *
        from ({query})
    """

    if args.aggregate:
        query = f"""select
            p.ie_key
            {', p.title' if 'title' in pl_columns else ''}
            , p.category
            , p.profile
            , coalesce(p.path, "Playlist-less media") path
            {', sum(media.duration) duration' if 'duration' in m_columns else ''}
            {', sum(media.size) size' if 'size' in m_columns else ''}
            , count(*) count
        from media
        left join ({query}) p on {db.get_playlists_join(args)}
        group by coalesce(p.path, "Playlist-less media")
        order by category nulls last, profile, p.path"""

    printer(args, query, bindings)


def dlstatus() -> None:
    args = parse_args(
        prog="library dlstatus",
        usage="""library dlstatus [database]

    Print download queue groups

        library dlstatus video.db
        ╒═════════════╤════════════════════╤═══════════╤═════════╤════════════════╕
        │ ie_key      │ category           │ profile   │   count │ duration       │
        ╞═════════════╪════════════════════╪═══════════╪═════════╪════════════════╡
        │ Dailymotion │ 71_Mealtime_Videos │ video     │     277 │                │
        ├─────────────┼────────────────────┼───────────┼─────────┼────────────────┤
        │ Vimeo       │ 71_Mealtime_Videos │ video     │     442 │                │
        ├─────────────┼────────────────────┼───────────┼─────────┼────────────────┤
        │ Youtube     │ 71_Mealtime_Videos │ video     │   30185 │ 1 year, 3      │
        │             │                    │           │         │ months, 7 days │
        │             │                    │           │         │ and 15 hours   │
        ├─────────────┼────────────────────┼───────────┼─────────┼────────────────┤
        │ Dailymotion │ 75_MovieQueue      │ video     │      84 │                │
        ├─────────────┼────────────────────┼───────────┼─────────┼────────────────┤
        │ Vimeo       │ 75_MovieQueue      │ video     │      75 │                │
        ├─────────────┼────────────────────┼───────────┼─────────┼────────────────┤
        │ Youtube     │ 75_MovieQueue      │ video     │   20079 │ 8 months, 25   │
        │             │                    │           │         │ days, 19 hours │
        │             │                    │           │         │ and 18 minutes │
        ╘═════════════╧════════════════════╧═══════════╧═════════╧════════════════╛
""",
    )

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    if args.delete:
        return delete_playlists(args, args.delete)

    m_columns = args.db["media"].columns_dict
    query, bindings = construct_query(args)
    query = f"""select
        p.profile
        {', media.ie_key' if 'ie_key' in m_columns else ''}
        , coalesce(p.category, "Playlist-less media") category
        , count(*) FILTER(WHERE time_modified=0) never_downloaded
        {', sum(media.duration) duration' if 'duration' in m_columns else ''}
        {', count(*) FILTER(WHERE time_modified>0 AND error IS NOT NULL) errors' if 'error' in m_columns else ''}
        --{', group_concat(distinct media.error) error_descriptions' if 'error' in m_columns else ''}
    from media
    left join ({query}) p on {db.get_playlists_join(args)}
    where 1=1
        and media.time_downloaded=0
        and media.time_deleted=0
    group by p.ie_key, p.category, p.profile
    order by p.category nulls last, p.profile"""

    printer(args, query, bindings)
