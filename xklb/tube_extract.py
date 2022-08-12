import argparse
import math
import os
import shutil
import sys
import tempfile
import textwrap
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from sqlite3 import OperationalError
from timeit import default_timer as timer
from typing import Dict, List, Tuple

import humanize
import numpy as np
import pandas as pd
import yt_dlp
from tabulate import tabulate

from xklb.db import sqlite_con
from xklb.tube_actions import default_ydl_opts
from xklb.utils import (
    argparse_dict,
    combine,
    filter_None,
    log,
    safe_unpack,
    single_column_tolist,
    stop,
)


def parse_args(action):
    parser = argparse.ArgumentParser()
    parser.add_argument("db", nargs="?", default="tube.db")
    if action == "add":
        parser.add_argument("playlists", nargs="+")
        parser.add_argument("-f", "--overwrite-db", action="store_true", help="Delete db file before scanning")
        parser.add_argument(
            "--lightweight",
            "-lw",
            action="store_true",
            help="lightweight add playlist: Use with --yt-dlp-config download-archive=archive.txt to inform tubeadd",
        )
    elif action == "update":
        parser.add_argument("playlists", nargs="*")

    parser.add_argument(
        "--yt-dlp-config",
        "-yt-dlp-config",
        nargs=1,
        action=argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default yt-dlp configuration",
    )
    parser.add_argument("-safe", "--safe", action="store_true", help="Skip generic URLs")

    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    args.action = action
    log.info(filter_None(args.__dict__))

    if args.action == "add":
        if args.overwrite_db:
            Path(args.db).unlink(missing_ok=True)
        Path(args.db).touch()
    args.con = sqlite_con(args.db)

    ydl_opts = {**default_ydl_opts, **args.yt_dlp_config}
    log.info(filter_None(ydl_opts))

    args.ydl_opts = ydl_opts
    return args


def supported(url):  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def consolidate(playlist_path, v):
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
        "epoch",
        "license",
        "timestamp",
        "track",
        "subtitles",
        "comments",
        "author",
        "text",
        "parent",
        "root",
        "filesize",
        "source_preference",
        "video_ext",
        "audio_ext",
        "http_headers",
        "User-Agent",
        "Accept",
        "Accept-Language",
        "Sec-Fetch-Mode",
        "navigate",
        "Cookie",
        "playlist_count",
        "n_entries",
        "playlist_autonumber",
        "availability",
        "formats",
        "requested_formats",
        "requested_entries",
        "thumbnails",
        "playlist_count",
        'playlist_id',
        'playlist_title',
        'playlist_uploader',
        'playlist_uploader_id',
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
    cv["path"] = safe_unpack(v.pop("webpage_url", None), v.pop("url", None), v.pop("original_url", None))
    cv["size"] = v.pop("filesize_approx", None)
    cv["time_created"] = upload_date
    duration = v.pop("duration", None)
    cv["duration"] = 0 if not duration else int(duration)
    cv["play_count"] = 0
    cv["language"] = v.pop("language", None)
    cv["tags"] = combine(v.pop("description", None), v.pop("categories", None), v.pop("tags", None))
    cv["id"] = v.pop("id")
    cv["ie_key"] = safe_unpack(v.pop("ie_key", None), v.pop("extractor_key", None), v.pop("extractor", None))
    cv["title"] = safe_unpack(v.pop("title", None), v.get("playlist_title"))
    cv["view_count"] = v.pop("view_count", None)
    cv["width"] = v.pop("width", None)
    cv["height"] = v.pop("height", None)
    fps = v.pop("fps", None)
    cv["fps"] = 0 if not fps else int(fps)
    cv["average_rating"] = v.pop("average_rating", None)
    cv["live_status"] = v.pop("live_status", None)
    cv["age_limit"] = v.pop("age_limit", None)
    cv["playlist_path"] = playlist_path
    cv["uploader"] = safe_unpack(
        v.pop("uploader_url", None),
        v.pop("channel_url", None),
        v.pop("uploader", None),
        v.pop("channel", None),
        v.pop("uploader_id", None),
        v.pop("channel_id", None),
    )

    if v != {}:
        log.info("Extra data %s", v)
        # breakpoint()

    return cv


def playlist_known(args, playlist_path):
    try:
        known = args.con.execute("select 1 from playlists where path=?", [playlist_path]).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return known[0]


def video_known(args, playlist_path, path):
    try:
        known = args.con.execute(
            "select 1 from media where playlist_path=? and path=?", [playlist_path, path]
        ).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return known[0]


def save_entries(args, entries):
    if entries:
        entriesDF = pd.DataFrame(entries)
        entriesDF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
            "media",
            con=args.con,
            if_exists="append",
            index=False,
            chunksize=70,
            method="multi",
        )


def log_problem(args, playlist_path):
    if args.action == "add":
        log.warning("Could not add playlist %s", playlist_path)
    else:
        log.warning("Start of known playlist reached %s", playlist_path)


def process_playlist(args, playlist_path) -> (List[Dict] | None):
    class ExistingPlaylistVideoReached(yt_dlp.DownloadCancelled):
        pass

    class AddToArchivePP(yt_dlp.postprocessor.PostProcessor):
        current_video_count = 0

        def run(self, info):
            entry = self._add_media(deepcopy(info))
            self._add_playlist(deepcopy(info), entry)

            self.current_video_count += 1
            sys.stdout.write("\033[K\r")
            print(f"{playlist_path}: added {self.current_video_count} videos", end="\r", flush=True)
            return [], info

        def _add_media(self, entry):
            entry = consolidate(playlist_path, entry)
            if video_known(args, playlist_path, entry["path"]):
                raise ExistingPlaylistVideoReached
            save_entries(args, [entry])
            return entry

        def _add_playlist(self, pl, entry):
            pl = dict(
                ie_key=safe_unpack(pl.get("ie_key"), pl.get("extractor_key"), pl.get("extractor")),
                title=pl.get("playlist_title"),
                path=playlist_path,
                uploader=safe_unpack(pl.get("playlist_uploader_id"), pl.get("playlist_uploader")),
                id=pl.get("playlist_id"),
            )
            if entry["path"] == pl["path"] or not pl.get('id'):
                log.warning("Importing playlist-less media %s", pl["path"])
            elif playlist_known(args, playlist_path):
                pass
            else:
                plDF = pd.DataFrame([pl])
                plDF.convert_dtypes().to_sql("playlists", con=args.con, if_exists="append", index=False)

    with yt_dlp.YoutubeDL(args.ydl_opts) as ydl:
        ydl.add_post_processor(AddToArchivePP(), when="pre_process")

        try:
            pl = ydl.extract_info(playlist_path, download=False, process=True)
        except ExistingPlaylistVideoReached:
            log_problem(args, playlist_path)
        else:
            if not pl:
                log_problem(args, playlist_path)


def get_playlists(args):
    try:
        known_playlists = single_column_tolist(args.con.execute("select path from playlists").fetchall(), "path")
    except OperationalError:
        known_playlists = []
    return known_playlists


def tube_add():
    args = parse_args("add")
    known_playlists = get_playlists(args)

    for playlist in args.playlists:
        if playlist in known_playlists:
            log.warning("Skipping known playlist: %s", playlist)
            continue

        if args.safe and not supported(playlist):
            log.warning("[safe_mode] unsupported playlist: %s", playlist)
            continue

        start = timer()
        process_playlist(args, playlist)
        end = timer()
        log.info(f"{end - start:.1f} seconds to add new playlist and fetch videos")


def tube_update():
    args = parse_args("update")
    known_playlists = get_playlists(args)

    for playlist in args.playlists or get_playlists(args):

        if playlist not in known_playlists:
            log.warning("Skipping unknown playlist: %s", playlist)
            continue

        start = timer()
        process_playlist(args, playlist)
        end = timer()
        log.info(f"{end - start:.1f} seconds to update playlist")


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
