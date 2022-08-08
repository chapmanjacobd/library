import argparse
import shutil
import tempfile
from pathlib import Path
from timeit import default_timer as timer
from typing import Dict

import pandas as pd
import yt_dlp

from xklb.db import sqlite_con
from xklb.utils import argparse_dict, filter_None, log

# TODO: add cookiesfrombrowser: ('firefox', ) as a default
# cookiesfrombrowser: ('vivaldi', ) # should not crash if not installed ?

default_ydl_opts = {
    # "writesubtitles": True,
    # "writeautomaticsub": True,
    # "subtitleslangs": "en.*,EN.*",
    # "playliststart": 20000, # an optimization needs to be made in yt-dlp to support some form of background backfilling/pagination. 2000-4000 takes 40 seconds instead of 20.
    "skip_download": True,
    "break_on_existing": True,
    "break_per_url": True,
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


def supported(url):  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def fetch_playlist(ydl_opts, playlist) -> Dict | None:
    # if not supported(playlist):
    #     return None

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        playlist_dict = ydl.extract_info(playlist, download=False)

        if not playlist_dict:
            return

        raise

        playlist_dict.pop("availability", None)
        playlist_dict.pop("formats", None)
        playlist_dict.pop("requested_formats", None)
        playlist_dict.pop("thumbnails", None)

        playlist_dict["playlist_count"] = playlist_dict.get("playlist_count") or len(playlist_dict)

        if playlist_dict.get("entries"):
            for v in playlist_dict["entries"]:
                v.pop("thumbnails", None)
                # v.pop("_type", None)
                # v.pop("availability", None)
                # v.pop("description", None)
                # v.pop("live_status", None)
                # v.pop("release_timestamp", None)
                # v.pop("view_count", None)
                # v.pop("upload_date", None)

                v["channel"] = v.get("channel") or v.get("channel_id") or playlist_dict.get("channel")
                v["path"] = v.get("original_url") or playlist_dict.get("original_url")
                v["playlist_count"] = v.get("playlist_count") or playlist_dict.get("playlist_count")
                v["playlist_title"] = playlist_dict.get("title")
                v["title"] = v.get("title") or playlist_dict.get("title")
                v["uploader"] = v.get("uploader") or playlist_dict.get("uploader")

        if playlist_dict.get("entries") is None:
            video_dict = dict(
                channel=playlist_dict.get("channel"),
                id=playlist_dict.get("id"),
                ie_key=playlist_dict.get("extractor_key"),
                path=playlist_dict.get("original_url"),
                playlist_count=1,
                title=playlist_dict.get("title"),
                uploader=playlist_dict.get("uploader"),
            )
            playlist_dict = {**video_dict, "entries": [video_dict]}

        return playlist_dict


def create_download_archive(args):
    user_download_archive = args.yt_dlp_options.pop("download_archive", None)
    download_archive_temp = tempfile.mktemp()

    query = "select distinct ie_key, id from entries"
    media = pd.DataFrame([dict(r) for r in args.con.execute(query).fetchall()])

    raise  # maybe use broadcasting

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
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default yt-dlp configuration",
    )
    args = parser.parse_args()
    log.info(filter_None(args.__dict__))

    args.con = sqlite_con(args.db)

    ydl_opts = {**default_ydl_opts, **args.yt_dlp_opts}
    log.info(filter_None(ydl_opts))

    if update:
        download_archive_temp = create_download_archive(args)
        ydl_opts = {**ydl_opts, "download_archive": download_archive_temp}

    return args, ydl_opts


def tube_add(args):
    args, ydl_opts = parse_args()

    for playlist in args.playlists:
        start = timer()
        pl = fetch_playlist(ydl_opts, playlist)
        end = timer()
        log.warning(end - start)
        if not pl:
            print("Could not process", playlist)
            continue

        entries = pl.pop("entries")
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

        """
        entries -> media
        url -> path

        playlists -> playlists

        list the undownloaded in a log (combine ytURE with retry functionality

        mpv --script-opts=ytdl_hook-try_ytdl_first=yes
        catt

        break on existing
        use sqlite data to create archive log (combine with actual archive log) in temp file to feed into yt-dlp
        """


def tube_update(args):
    args, ydl_opts = parse_args(update=True)

    if args.playlists:
        pass
    else:  # update all
        pass

    Path(ydl_opts["download_archive"]).unlink()
