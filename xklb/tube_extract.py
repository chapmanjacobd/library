import argparse
import csv
import math
import os
import shutil
import tempfile
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from timeit import default_timer as timer
from typing import Dict, List, Tuple

import humanize
import numpy as np
import pandas as pd
import yt_dlp
from rich import inspect, print
from tabulate import tabulate

from xklb.db import sqlite_con
from xklb.tube_actions import default_ydl_opts
from xklb.utils import (
    argparse_dict,
    combine,
    filter_None,
    log,
    safe_unpack,
    stop,
)


def create_download_archive(args):
    user_download_archive = args.yt_dlp_options.pop("download_archive", None)
    download_archive_temp = tempfile.mktemp()

    query = "select distinct ie_key, id from entries"
    media = pd.DataFrame([dict(r) for r in args.con.execute(query).fetchall()])

    breakpoint()  # maybe use broadcasting

    ax_txt = "\n".join(list(map(lambda m: f"{m['ie_key'].lower()} {m['id']}", media.to_records())))
    Path(download_archive_temp).write_text(ax_txt)

    if user_download_archive:
        with open(download_archive_temp, "ab") as wfd:
            for f in [user_download_archive]:
                with open(f, "rb") as fd:
                    shutil.copyfileobj(fd, wfd)
                    wfd.write(b"\n")

    return download_archive_temp


def parse_args(action):
    parser = argparse.ArgumentParser()
    parser.add_argument("db", nargs="?", default="tube.db")

    parser.add_argument(
        "--yt-dlp-config",
        "-yt-dlp-config",
        nargs="*",
        action=argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default yt-dlp configuration",
    )
    parser.add_argument("-safe", "--safe", action="store_true", help="Skip generic URLs")
    if action == "add":
        parser.add_argument("playlists", nargs="+")
        parser.add_argument("-f", "--overwrite-db", action="store_true", help="Delete db file before scanning")
        parser.add_argument(
            "--lightweight",
            "-lw",
            action="store_true",
            help="lightweight add playlist: Use with --yt-dlp-config download-archive=archive.txt to inform tubeadd",
        )
    if action == "update":
        parser.add_argument("playlists", nargs="?")

    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    log.info(filter_None(args.__dict__))

    if action == "add":
        if args.overwrite_db:
            Path(args.db).unlink(missing_ok=True)
        Path(args.db).touch()
    args.con = sqlite_con(args.db)

    ydl_opts = {**default_ydl_opts, **args.yt_dlp_config}
    log.info(filter_None(ydl_opts))

    if action == "update" or args.lightweight:
        download_archive_temp = create_download_archive(args)
        ydl_opts = {
            **ydl_opts,
            "download_archive": download_archive_temp,
            "break_on_existing": True,
            "break_per_url": True,
        }

    args.ydl_opts = ydl_opts
    return args


def supported(url):  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def fetch_playlist(args, playlist) -> Tuple[(None | Dict), (None | List[Dict])]:
    with yt_dlp.YoutubeDL(args.ydl_opts) as ydl:
        pl = ydl.extract_info(playlist, download=False)

        if not pl:
            return None, None

        pl.pop("availability", None)
        pl.pop("formats", None)
        pl.pop("requested_formats", None)
        pl.pop("requested_entries", None)
        pl.pop("thumbnails", None)
        pl.pop("playlist_count", None)

        def consolidate(v):
            ignore_keys = [
                "thumbnail",
                "thumbnails",
                "availability",
                "playable_in_embed",
                "is_live",
                "was_live",
                "modified_date",
                "release_timestamp",
                "comment_count",
                "chapters",
                "like_count",
                "channel_follower_count",
                "webpage_url_basename",
                "webpage_url_domain",
                "playlist",
                "playlist_index",
                "display_id",
                "fulltitle",
                "duration_string",
                "requested_subtitles",
                "format",
                "format_id",
                "ext",
                "protocol",
                "format_note",
                "tbr",
                "resolution",
                "dynamic_range",
                "vcodec",
                "vbr",
                "stretched_ratio",
                "acodec",
                "abr",
                "asr",
            ]

            if v.get("title") in ["[Deleted video]", "[Private video]"]:
                return None

            for k in list(v):
                if k.startswith("_") or k in ignore_keys:
                    v.pop(k, None)

            upload_date = v.pop("upload_date", None)
            if upload_date:
                upload_date = int(datetime.strptime(upload_date, "%Y%m%d").timestamp())

            cv = dict()
            cv["path"] = safe_unpack(
                v.pop("url", None),
                v.pop("webpage_url", None),
                v.pop("original_url", None),
                pl.get("webpage_url"),
                pl.get("original_url"),
            )
            cv["size"] = v.pop("filesize_approx", None)
            cv["time_created"] = upload_date
            cv["duration"] = v.pop("duration", None)
            cv["play_count"] = 0
            cv["language"] = v.pop("language", None)
            cv["tags"] = combine(v.pop("description", None), v.pop("categories", None), v.pop("tags", None))
            cv["id"] = v.pop("id")
            cv["ie_key"] = safe_unpack(v.pop("ie_key", None), v.pop("extractor_key", None), v.pop("extractor", None))
            cv["title"] = safe_unpack(v.pop("title", None), pl.get("title"))
            cv["view_count"] = v.pop("view_count", None)
            cv["width"] = v.pop("width", None)
            cv["height"] = v.pop("height", None)
            cv["fps"] = v.pop("fps", None)
            cv["average_rating"] = v.pop("average_rating", None)
            cv["live_status"] = v.pop("live_status", None)
            cv["age_limit"] = v.pop("age_limit", None)
            cv["playlist_path"] = safe_unpack(pl.get("webpage_url"), pl.get("original_url"))
            cv["uploader_url"] = safe_unpack(
                v.pop("uploader_url", None),
                v.pop("channel_url", None),
                v.pop("uploader", None),
                v.pop("channel", None),
                v.pop("uploader_id", None),
                v.pop("channel_id", None),
                pl.get("uploader", None),
                pl.get("channel", None),
            )

            if v != {}:
                log.info("Extra data %s", v)
                # breakpoint()

            return cv

        entries = pl.pop("entries", None)
        if entries is None:
            entry = consolidate(pl)
            log.info("No entries %s", entry)
            if not entry:
                return None, None
            return None, [entry]

        entries = list(filter(None, [consolidate(v) for v in entries if v]))
        print(f"Downloaded {len(entries)} entries from playlist '{pl['title']}'")

        return filter_None(consolidate(pl)), entries


def tube_add():
    args = parse_args("add")

    for playlist in args.playlists:
        if args.safe and not supported(playlist):
            continue

        start = timer()
        pl, entries = fetch_playlist(args, playlist)
        end = timer()
        log.info(f"{end - start:.1f} seconds to fetch playlist")
        if not entries:
            print("Could not process", playlist)
            continue

        if pl:
            plDF = pd.DataFrame([pl])
            plDF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
                "playlists",
                con=args.con,
                if_exists="append",
                index=False,
            )
        entriesDF = pd.DataFrame(entries)
        entriesDF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
            "media",
            con=args.con,
            if_exists="append",
            index=False,
            chunksize=70,
            method="multi",
        )


def human_time(hours):
    if hours is None or np.isnan(hours):
        return None
    return humanize.precisedelta(timedelta(hours=int(hours), minutes=math.ceil(hours % 1 * 60)), minimum_unit="minutes")


def tube_list():
    parser = argparse.ArgumentParser()
    parser.add_argument("db", nargs="?", default="tube.db")
    parser.add_argument(
        "--print",
        "-p",
        nargs="*",
        default="p",
        choices=["p", "f", "a"],
        help="""tubelist a -- means print an aggregate report
tubelist f -- means print only filenames -- useful for piping to other utilities like xargs or GNU Parallel""",
    )
    parser.add_argument(
        "--delete",
        "--remove",
        "--erase",
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
        args.con.execute(
            "delete from media where playlist_path in (" + ",".join(["?"] * len(args.delete)) + ")", (*args.delete,)
        )
        args.con.execute(
            "delete from playlists where path in (" + ",".join(["?"] * len(args.delete)) + ")", (*args.delete,)
        )
        args.con.commit()
        stop()

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

    if "f" in args.print:
        unix_loves_lines = db_resp[["path"]].to_csv(index=False, header=False, sep="\t", quoting=csv.QUOTE_NONE)
        print(unix_loves_lines.strip())
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


def tube_update():
    args = parse_args("update")

    if args.playlists:
        breakpoint()
        pass
    else:  # update all
        query = "select distinct * from playlists"
        media = pd.DataFrame([dict(r) for r in args.con.execute(query).fetchall()])

        breakpoint()

    Path(args.ydl_opts["download_archive"]).unlink()
