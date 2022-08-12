import argparse
import math
import os
import textwrap
from datetime import timedelta
from pathlib import Path

import humanize
import numpy as np
import pandas as pd
from tabulate import tabulate

from xklb.db import sqlite_con
from xklb.fs_actions import parse_args, process_actions
from xklb.utils import CAST_NOW_PLAYING, Subcommand, filter_None, log, stop

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


def tube_watch():
    args = parse_args("tube.db", default_chromecast="Living Room TV")
    args.action = Subcommand.tubewatch

    process_actions(args)


def tube_listen():
    args = parse_args("tube.db", default_chromecast="Xylo and Orchestra")
    args.action = Subcommand.tubelisten

    try:
        process_actions(args)
    finally:
        if args.chromecast:
            Path(CAST_NOW_PLAYING).unlink(missing_ok=True)


def human_time(hours):
    if hours is None or np.isnan(hours):
        return None
    return humanize.precisedelta(timedelta(hours=int(hours), minutes=math.ceil(hours % 1 * 60)), minimum_unit="minutes")


def printer(args):
    query = "select distinct ie_key, title, path from playlists"
    if "a" in args.print:
        query = f"""select
            playlists.ie_key
            , playlists.title
            , coalesce(playlists.path, "Playlist-less videos") path
            , sum(media.duration/60.0/60.0) hours
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
        tbl[["path"]] = tbl[["path"]].applymap(
            lambda x: textwrap.fill(x, max(10, os.get_terminal_size().columns - (15 * len(tbl.columns))))
        )
        if "uploader_url" in tbl.columns:
            tbl[["uploader_url"]] = tbl[["uploader_url"]].applymap(
                lambda x: None
                if x is None
                else textwrap.fill(x, max(10, os.get_terminal_size().columns - (40 * len(tbl.columns))))
            )

        if "size" in tbl.columns:
            tbl[["size"]] = tbl[["size"]].applymap(lambda x: None if x is None else humanize.naturalsize(x))
        if "hours" in tbl.columns:
            tbl[["hours"]] = tbl[["hours"]].applymap(lambda x: None if x is None else human_time(x))

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore

        if "hours" in db_resp.columns:
            summary = db_resp.sum(numeric_only=True)
            hours = summary.get("hours") or 0.0
            print("Total duration:", human_time(hours))

    stop()


def delete_playlists(args, playlists):
    args.con.execute(
        "delete from media where playlist_path in (" + ",".join(["?"] * len(playlists)) + ")", (*playlists,)
    )
    args.con.execute("delete from playlists where path in (" + ",".join(["?"] * len(playlists)) + ")", (*playlists,))
    args.con.commit()


def tube_list():
    parser = argparse.ArgumentParser()
    parser.add_argument("db", nargs="?", default="tube.db")
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
        "-d",
        nargs="+",
        help="""lb tubelist -rm https://vimeo.com/canal180 -- removes the playlist/channel and all linked videos""",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    log.info(filter_None(args.__dict__))

    args.con = sqlite_con(args.db)

    if args.delete:
        delete_playlists(args, args.delete)
        stop()

    printer(args)
