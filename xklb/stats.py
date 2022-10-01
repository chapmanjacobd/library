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


def construct_tubelist_query(args) -> Tuple[str, dict]:
    columns = [c.name for c in args.db["media"].columns]
    cf = []
    bindings = {}

    cf.extend([" and " + w for w in args.where])

    args.table = "playlists"
    if args.db["playlists"].detect_fts():
        if args.include:
            args.table = db.fts_search(args, bindings)
        elif args.exclude:
            construct_search_bindings(args, bindings, cf, columns)
    else:
        construct_search_bindings(args, bindings, cf, columns)

    args.sql_filter = " ".join(cf)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""

    query = f"""SELECT
        *
    FROM {args.table}
    WHERE 1=1
    {args.sql_filter}
    ORDER BY 1=1
        {', ' + args.sort}
        , random()
    {LIMIT}
    """

    return query, bindings


def get_playlists_join(media_columns):
    join = "(p.ie_key = 'Local' and media.path like p.path || '%' ) "
    if "playlist_path" in media_columns:
        join += "or (p.ie_key != 'Local' and p.path = media.playlist_path)"
    return join


def printer(args, query, bindings) -> None:
    columns = [c.name for c in args.db["playlists"].columns]

    if args.aggregate:
        query = f"""select
            p.time_deleted
            , p.ie_key
            {', p.title' if 'title' in columns else ''}
            , p.category
            , p.profile
            , coalesce(p.path, "Playlist-less media") path
            , sum(media.duration) duration
            , sum(media.size) size
            , count(*) count
        from media
        left join ({query}) p on {get_playlists_join(columns)}
        group by coalesce(p.path, "Playlist-less media")
        order by p.time_deleted > 0 desc, category, profile, p.path"""

    media = list(args.db.query(query, bindings))

    media = utils.list_dict_filter_bool(media)
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
        prog="library tubelist",
        usage="""library tubelist [database] [--print {p,f,a}] [--delete ...]

    List of Playlists

        library tubelist
        ╒══════════╤════════════════════╤══════════════════════════════════════════════════════════════════════════╕
        │ ie_key   │ title              │ path                                                                     │
        ╞══════════╪════════════════════╪══════════════════════════════════════════════════════════════════════════╡
        │ Youtube  │ Highlights of Life │ https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n │
        ╘══════════╧════════════════════╧══════════════════════════════════════════════════════════════════════════╛

    Aggregate Report of Videos in each Playlist

        library tubelist -p a
        ╒══════════╤════════════════════╤══════════════════════════════════════════════════════════════════════════╤═══════════════╤═════════╕
        │ ie_key   │ title              │ path                                                                     │ duration      │   count │
        ╞══════════╪════════════════════╪══════════════════════════════════════════════════════════════════════════╪═══════════════╪═════════╡
        │ Youtube  │ Highlights of Life │ https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n │ 53.28 minutes │      15 │
        ╘══════════╧════════════════════╧══════════════════════════════════════════════════════════════════════════╧═══════════════╧═════════╛
        1 playlist
        Total duration: 53.28 minutes

    Print only playlist urls:
        Useful for piping to other utilities like xargs or GNU Parallel.
        library tubelist -p f
        https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n

    Remove a playlist/channel and all linked videos:
        library tubelist --remove https://vimeo.com/canal180

    """,
    )

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    if args.delete:
        return delete_playlists(args, args.delete)

    printer(args, *construct_tubelist_query(args))


def dlstatus() -> None:
    args = parse_args(
        prog="library dlstatus",
        usage="""library dlstatus [database]

    Print download queue groups

        library dlstatus dl.db
        TODO: update image
""",
    )

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    if args.delete:
        return delete_playlists(args, args.delete)

    columns = [c.name for c in args.db["playlists"].columns]
    query, bindings = construct_tubelist_query(args)
    query = f"""select
        p.ie_key
        , p.category
        , p.profile
        , time_downloaded
        , avg(time_downloaded) avg_time_since_download
        , sum(media.duration) duration
        , sum(media.size) size
        , count(*) count
    from media
    left join ({query}) p on {get_playlists_join(columns)}
    where category != '{consts.BLOCK_THE_CHANNEL}'
    group by time_downloaded > 0, p.ie_key, p.category, p.profile
    order by time_downloaded > 0 desc, sum(time_downloaded > 0), category, profile"""

    printer(args, query, bindings)
