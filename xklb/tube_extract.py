import argparse
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from timeit import default_timer as timer
from typing import Dict, List, Tuple, Union

import pandas as pd
import yt_dlp
from rich import print

from xklb.db import sqlite_con
from xklb.tube_actions import default_ydl_opts
from xklb.utils import (
    argparse_dict,
    combine,
    filter_None,
    log,
    safe_unpack,
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


def parse_args(update=False):
    parser = argparse.ArgumentParser()
    parser.add_argument("db", nargs="?", default="tube.db")
    parser.add_argument("playlists", nargs="?" if update else "+")
    parser.add_argument(
        "--yt-dlp-config",
        "-yt-dlp-config",
        nargs="*",
        action=argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default yt-dlp configuration",
    )
    parser.add_argument(
        "-update",
        "--update",
        action="store_true",
        help="lightweight add playlist: Use with --yt-dlp-config download-archive=archive.txt to inform tubeadd",
    )
    parser.add_argument("-safe", "--safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("-f", "--overwrite-db", action="store_true", help="Delete db file before scanning")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    log.info(filter_None(args.__dict__))

    if args.overwrite_db:
        Path(args.db).unlink(missing_ok=True)

    Path(args.db).touch()
    args.con = sqlite_con(args.db)

    ydl_opts = {**default_ydl_opts, **args.yt_dlp_config}
    log.info(filter_None(ydl_opts))

    if update or args.update:
        download_archive_temp = create_download_archive(args)
        ydl_opts = {
            **ydl_opts,
            "download_archive": download_archive_temp,
            "break_on_existing": True,
            "break_per_url": True,
        }

    return args, ydl_opts


def supported(url):  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def fetch_playlist(ydl_opts, playlist) -> Union[Tuple[Dict | None, List[Dict]],Tuple[None, None]]:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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
                'modified_date',
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

            if v.get('title') in ["[Deleted video]", "[Private video]"]:
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
                pl.get("original_url"),
            )
            cv["size"] = v.pop("filesize_approx", None)
            cv["time_created"] = upload_date
            cv["duration"] = v.pop("duration", None)
            cv["play_count"] = 0
            cv["language"] = v.pop("language", None)
            cv["tags"] = combine(v.pop("description", None), v.pop("categories", None), v.pop("tags", None))
            cv["id"] = v.pop("id")
            cv["ie_key"] = safe_unpack(v.pop("extractor_key", None), v.pop("extractor"))
            cv["playlist_path"] = safe_unpack(pl.get("original_url"), pl.get("webpage_url"))
            cv["view_count"] = v.pop("view_count", None)
            cv["width"] = v.pop("width", None)
            cv["height"] = v.pop("height", None)
            cv["fps"] = v.pop("fps", None)
            cv["average_rating"] = v.pop("average_rating", None)
            cv["live_status"] = v.pop("live_status", None)
            cv["age_limit"] = v.pop("age_limit", None)
            cv["title"] = safe_unpack(v.pop("title", None), pl.get("title"))
            cv["uploader"] = safe_unpack(
                v.pop("uploader_url", None),
                v.pop("uploader", None),
                v.pop("uploader_id", None),
                pl.get("uploader"),
            )
            cv["channel"] = safe_unpack(
                v.pop("channel_url", None),
                v.pop("channel", None),
                v.pop("channel_id", None),
                pl.get("channel"),
            )

            if v != {}:
                log.info("Extra data %s", v)
                breakpoint()

            return cv

        entries = pl.pop("entries", None)
        if pl.get("entries") is None:
            entry = consolidate(pl)
            if entry:
                return None, [entry]
            return None, None

        entries = [consolidate(v) for v in entries]
        print(f"Got {len(entries)} entries from playlist '{pl['title']}'")

        breakpoint()

        return pl, entries


def tube_add():
    args, ydl_opts = parse_args()

    for playlist in args.playlists:
        if args.safe and not supported(playlist):
            continue

        start = timer()
        pl, entries = fetch_playlist(ydl_opts, playlist)
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
        DF = pd.DataFrame(list(filter(None, entries)))
        DF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
            "media",
            con=args.con,
            if_exists="append",
            index=False,
            chunksize=70,
            method="multi",
        )


def tube_update():
    args, ydl_opts = parse_args(update=True)

    if args.playlists:
        pass
    else:  # update all
        pass

    Path(ydl_opts["download_archive"]).unlink()
