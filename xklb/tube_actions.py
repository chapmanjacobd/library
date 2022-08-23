import argparse

import humanize
import pandas as pd
from tabulate import tabulate

from xklb.db import sqlite_con
from xklb.fs_actions import parse_args, process_actions
from xklb.utils import SC, filter_None, human_time, log, resize_col
from xklb.utils_player import delete_playlists

# TODO: add cookiesfrombrowser: ('firefox', ) as a default
# cookiesfrombrowser: ('vivaldi', ) # should not crash if not installed ?

default_ydl_opts = {
    # "writesubtitles": True,
    # "writeautomaticsub": True,
    # "subtitleslangs": "en.*,EN.*",
    "lazy_playlist": True,
    "skip_download": True,
    "force_write_download_archive": True,
    "check_formats": False,
    "no_check_certificate": True,
    "no_warnings": True,
    "ignore_no_formats_error": True,
    "ignoreerrors": "only_download",
    "skip_playlist_after_errors": 20,
    "quiet": True,
    "dynamic_mpd": False,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "extract_flat": True,
    "clean_infojson": False,
    "playlistend": 20000,
    "rejecttitle": "|".join(
        [
            "Trailer",
            "Sneak Peek",
            "Preview",
            "Teaser",
            "Promo",
            "Crypto",
            "Montage",
            "Bitcoin",
            "Apology",
            " Clip",
            "Clip ",
            "Best of",
            "Compilation",
            "Top 10",
            "Top 9",
            "Top 8",
            "Top 7",
            "Top 6",
            "Top 5",
            "Top 4",
            "Top 3",
            "Top 2",
            "Top Ten",
            "Top Nine",
            "Top Eight",
            "Top Seven",
            "Top Six",
            "Top Five",
            "Top Four",
            "Top Three",
            "Top Two",
        ]
    ),
}


tube_include_string = (
    lambda x: f"""and (
    path like :include{x}
    OR tags like :include{x}
    OR title like :include{x}
)"""
)

tube_exclude_string = (
    lambda x: f"""and (
    path not like :exclude{x}
    AND tags not like :exclude{x}
    AND title not like :exclude{x}
)"""
)


def construct_tube_query(args):
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    for idx, inc in enumerate(args.include):
        cf.append(tube_include_string(idx))
        bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        cf.append(tube_exclude_string(idx))
        bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"

    args.sql_filter = " ".join(cf)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""SELECT path
        , title
        , duration
        , size
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM media
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


def tube_watch():
    args = parse_args(SC.tubewatch, "tube.db", default_chromecast="Living Room TV")
    process_actions(args, construct_tube_query)


def tube_listen():
    args = parse_args(SC.tubelisten, "tube.db", default_chromecast="Xylo and Orchestra")
    process_actions(args, construct_tube_query)


def printer(args):
    query = "select distinct ie_key, title, path from playlists"
    if "a" in args.print:
        query = f"""select
            playlists.ie_key
            , playlists.title
            , coalesce(playlists.path, "Playlist-less videos") path
            , sum(media.duration) duration
            , sum(media.size) size
            , count(*) count
        from media
        left join playlists on playlists.path = media.playlist_path
        group by coalesce(playlists.path, "Playlist-less videos")"""

    db_resp = pd.DataFrame([dict(r) for r in args.con.execute(query).fetchall()])
    db_resp.dropna(axis="columns", how="all", inplace=True)

    if "f" in args.print:
        print(db_resp[["path"]].to_string(index=False, header=False))
    else:
        tbl = db_resp.copy()

        tbl = resize_col(tbl, "path", 40)
        tbl = resize_col(tbl, "uploader_url")

        if "size" in tbl.columns:
            tbl[["size"]] = tbl[["size"]].applymap(lambda x: None if x is None else humanize.naturalsize(x))
        if "duration" in tbl.columns:
            tbl[["duration"]] = tbl[["duration"]].applymap(lambda x: None if x is None else human_time(x))

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore

        if "duration" in db_resp.columns:
            print(f"{len(db_resp)} items")
            summary = db_resp.sum(numeric_only=True)
            duration = summary.get("duration") or 0
            print("Total duration:", human_time(duration))


def tube_list():
    parser = argparse.ArgumentParser(prog="lb tubelist")
    parser.add_argument("database", nargs="?", default="tube.db")
    parser.add_argument("--db", "-db")
    parser.add_argument(
        "--print",
        "-p",
        nargs="*",
        default="p",
        choices=["p", "f", "a"],
        help="""tubelist -p a -- means print playlists in a table
tubelist -p a -- means print an aggregate report
tubelist -p f -- means print only playlist urls -- useful for piping to other utilities like xargs or GNU Parallel""",
    )
    parser.add_argument(
        "--delete",
        "--remove",
        "--erase",
        "--rm",
        "-rm",
        nargs="+",
        help="""lb tubelist -rm https://vimeo.com/canal180 -- removes the playlist/channel and all linked videos""",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    log.info(filter_None(args.__dict__))

    args = parser.parse_args()

    if args.db:
        args.database = args.db

    args.con = sqlite_con(args.database)

    if args.delete:
        return delete_playlists(args, args.delete)

    printer(args)
