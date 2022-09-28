import argparse, operator
from copy import deepcopy
from typing import Tuple

from tabulate import tabulate

from xklb import db, utils
from xklb.play_actions import construct_search_bindings, parse_args, process_playqueue
from xklb.player import delete_playlists
from xklb.utils import DEFAULT_PLAY_QUEUE, SC, human_time, log

tube_include_string = (
    lambda x: f"""and (
    media.path like :include{x}
    OR playlist_path like :include{x}
    OR tags like :include{x}
    OR media.title like :include{x}
)"""
)

tube_exclude_string = (
    lambda x: f"""and (
    media.path not like :exclude{x}
    AND playlist_path not like :exclude{x}
    AND tags not like :exclude{x}
    AND media.title not like :exclude{x}
)"""
)


def construct_tube_query(args) -> Tuple[str, dict]:
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    args.table = "media"
    if args.db["media"].detect_fts():
        if args.include:
            args.table = db.fts_search(args, bindings)
        elif args.exclude:
            construct_search_bindings(args, bindings, cf, tube_include_string, tube_exclude_string)
    else:
        construct_search_bindings(args, bindings, cf, tube_include_string, tube_exclude_string)

    if args.table == "media" and not args.print:
        limit = 60_000
        if args.random:
            limit = DEFAULT_PLAY_QUEUE * 2
        cf.append(f"and rowid in (select rowid from media order by random() limit {limit})")

    args.sql_filter = " ".join(cf)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""SELECT path
        , title
        , duration
        , size
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM {args.table}
    WHERE 1=1
    {args.sql_filter}
    {'and width < height' if args.portrait else ''}
    ORDER BY 1=1
        {',' + args.sort if args.sort else ''}
        {', path' if args.print or args.include or args.play_in_order > 0 else ''}
        , duration / size ASC
    {LIMIT} {OFFSET}
    """

    return query, bindings


def tube_watch() -> None:
    args = parse_args(SC.tubewatch, "tube.db", default_chromecast="Living Room TV")
    process_playqueue(args, construct_tube_query)


def tube_listen() -> None:
    args = parse_args(SC.tubelisten, "tube.db", default_chromecast="Xylo and Orchestra")
    process_playqueue(args, construct_tube_query)


def printer(args) -> None:
    query = "select distinct ie_key, title, path from playlists"
    if "a" in args.print:
        query = f"""select
            playlists.is_deleted
            , playlists.ie_key
            , playlists.title
            , playlists.category
            , playlists.profile download_profile
            , coalesce(playlists.path, "Playlist-less videos") path
            , sum(media.duration) duration
            , sum(media.size) size
            , count(*) count
        from media
        left join playlists on playlists.path = media.playlist_path
        group by coalesce(playlists.path, "Playlist-less videos")
        order by playlists.is_deleted desc, category, profile, playlists.path"""

    db_resp = list(args.db.query(query))

    if "f" in args.print:
        print("\n".join(list(map(operator.itemgetter("path"), db_resp))))
    else:
        tbl = deepcopy(db_resp)

        tbl = utils.col_resize(tbl, "path", 40)
        tbl = utils.col_resize(tbl, "uploader_url")

        utils.col_naturalsize(tbl, "size")
        utils.col_duration(tbl, "duration")

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore

        print(f"{len(db_resp)} playlists" if len(db_resp) >= 2 else "1 playlist")
        duration = sum(map(lambda m: m.get("duration") or 0, db_resp))
        if duration > 0:
            duration = human_time(duration)
            if not "a" in args.print:
                print("Total duration:", duration)


def tube_list() -> None:
    parser = argparse.ArgumentParser(
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
    parser.add_argument("database", nargs="?", default="tube.db")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--print", "-p", nargs="*", default="p", choices=["p", "f", "a"], help=argparse.SUPPRESS)
    parser.add_argument("--delete", "--remove", "--erase", "--rm", "-rm", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    if args.delete:
        return delete_playlists(args, args.delete)

    printer(args)
