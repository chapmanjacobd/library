import argparse, sys, tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from sqlite3 import OperationalError
from time import sleep
from timeit import default_timer as timer
from typing import Dict, List, Union
from urllib.error import HTTPError

import pandas as pd
import yt_dlp

from xklb import db, utils
from xklb.paths import SUB_TEMP_DIR, sanitize_url
from xklb.subtitle import subs_to_text
from xklb.tube_actions import default_ydl_opts
from xklb.utils import combine, log, safe_unpack


def parse_args(action, usage):
    parser = argparse.ArgumentParser(prog="lb tube" + action, usage=usage)
    parser.add_argument("database", nargs="?", default="tube.db")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    if action == "add":
        parser.add_argument("playlists", nargs="+")
    elif action == "update":
        parser.add_argument("playlists", nargs="*")
        parser.add_argument("--optimize", action="store_true", help="Optimize Database")

    parser.add_argument(
        "--yt-dlp-config",
        "-yt-dlp-config",
        nargs=1,
        action=utils.argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default yt-dlp configuration",
    )
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--no-sanitize", "-s", action="store_false", help="Don't sanitize some common URL parameters")

    parser.add_argument("--extra", "-extra", action="store_true", help="Get full metadata (takes a lot longer)")

    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.db = db.connect(args)

    ydl_opts = {**default_ydl_opts, **args.yt_dlp_config}
    log.info(utils.dict_filter_bool(ydl_opts))

    if args.playlists and not args.no_sanitize:
        args.playlists = [sanitize_url(args, path) for path in args.playlists]

    args.ydl_opts = ydl_opts

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def supported(url):  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def get_subtitle_text(ydl: yt_dlp.YoutubeDL, video_path, req_sub_dict):
    def dl_sub(url):
        temp_file = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)

        try:
            ydl.dl(temp_file, {"url": url}, subtitle=True)
        except HTTPError:
            log.info("Unable to download subtitles; skipping")
            sleep(5)
            return None
        else:
            return temp_file

    urls = [d["url"] for d in list(req_sub_dict.values())]
    paths = utils.conform([dl_sub(url) for url in urls])

    subs_text = subs_to_text(video_path, paths)
    [Path(p).unlink(missing_ok=True) for p in paths]

    return subs_text


def consolidate(ydl: yt_dlp.YoutubeDL, playlist_path, v):
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
        "playlist_id",
        "playlist_title",
        "playlist_uploader",
        "playlist_uploader_id",
        "audio_channels",
        "subtitles",
        "automatic_captions",
        "quality",
        "has_drm",
        "language_preference",
        "preference",
        "location",
    ]

    if v.get("title") in ["[Deleted video]", "[Private video]"]:
        return None

    for k in list(v):
        if k.startswith("_") or k in ignore_keys:
            v.pop(k, None)

    release_date = v.pop("release_date", None)
    upload_date = v.pop("upload_date", None) or release_date
    if upload_date:
        upload_date = int(datetime.strptime(upload_date, "%Y%m%d").timestamp())

    subtitles = v.pop("requested_subtitles", None)
    if subtitles:
        subtitles = get_subtitle_text(ydl, playlist_path, subtitles)

    cv = dict()
    cv["path"] = safe_unpack(v.pop("webpage_url", None), v.pop("url", None), v.pop("original_url", None))
    cv["size"] = v.pop("filesize_approx", None)
    cv["time_created"] = upload_date
    duration = v.pop("duration", None)
    cv["duration"] = 0 if not duration else int(duration)
    cv["play_count"] = 0
    cv["time_played"] = 0
    cv["language"] = v.pop("language", None)
    cv["tags"] = combine(v.pop("description", None), v.pop("categories", None), v.pop("tags", None), subtitles)
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
        known = args.db.execute("select 1 from playlists where path=?", [playlist_path]).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return known[0]


def video_known(args, playlist_path, path):
    try:
        known = args.db.execute(
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
            con=args.db.conn,
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


def process_playlist(args, playlist_path) -> Union[List[Dict], None]:
    class ExistingPlaylistVideoReached(yt_dlp.DownloadCancelled):
        pass

    class AddToArchivePP(yt_dlp.postprocessor.PostProcessor):
        current_video_count = 0

        def run(self, info):
            entry = self._add_media(deepcopy(info))
            self._add_playlist(deepcopy(info), entry)

            self.current_video_count += 1
            sys.stdout.write("\033[K\r")
            print(f"[{playlist_path}] Added {self.current_video_count} videos", end="\r", flush=True)
            return [], info

        def _add_media(self, entry):
            entry = consolidate(super, playlist_path, entry)  # type: ignore
            if entry:
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
            if entry["path"] == pl["path"] or not pl.get("id"):
                log.warning("Importing playlist-less media %s", pl["path"])
            elif playlist_known(args, playlist_path):
                pass
            else:
                plDF = pd.DataFrame([pl])
                plDF.convert_dtypes().to_sql("playlists", con=args.db.conn, if_exists="append", index=False)

    with yt_dlp.YoutubeDL(args.ydl_opts) as ydl:
        ydl.add_post_processor(AddToArchivePP(), when="pre_process")

        try:
            pl = ydl.extract_info(playlist_path, download=False, process=True)
        except ExistingPlaylistVideoReached:
            log_problem(args, playlist_path)
        else:
            if not pl:
                log_problem(args, playlist_path)


def get_extra_metadata(args, playlist_path) -> Union[List[Dict], None]:
    with yt_dlp.YoutubeDL(
        {
            **args.ydl_opts,
            "subtitlesformat": "srt/best",
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en.*", "EN.*"],
            "extract_flat": False,
            "lazy_playlist": False,
            "skip_download": True,
            "check_formats": False,
            "ignoreerrors": True,
        }
    ) as ydl:
        videos = args.db.execute(
            """
                select path, ie_key, play_count, time_played from media
                where
                    width is null
                    and path not like '%playlist%'
                    and playlist_path = ?
                order by random()
                """,
            [playlist_path],
        ).fetchall()

        current_video_count = 0
        for path, ie_key, play_count, time_played in videos:
            entry = ydl.extract_info(path, ie_key=ie_key, download=False)
            if entry is None:
                continue

            entry = consolidate(ydl, playlist_path, entry)
            if entry is None:
                continue

            entry["play_count"] = play_count
            entry["time_played"] = time_played

            args.db.execute("DELETE FROM media where path = ? and ie_key = ?", [path, ie_key])
            save_entries(args, [entry])

            current_video_count += 1
            sys.stdout.write("\033[K\r")
            print(
                f"[{playlist_path}] {current_video_count} of {len(videos)} extra metadata fetched", end="\r", flush=True
            )


def get_playlists(args, include_playlistless_media=True):
    try:
        if include_playlistless_media:
            known_playlists = [d["path"] for d in args.db.query("select path from playlists order by random()")]

        else:
            known_playlists = [
                d["playlist_path"]
                for d in args.db.query(
                    """
                    select playlist_path from media
                    group by playlist_path
                    having count(playlist_path) > 1
                    order by random()
                    """
                )
            ]
    except OperationalError:
        known_playlists = []
    return known_playlists


def tube_add():
    args = parse_args(
        "add",
        usage="""lb tubeadd [database] playlists ...

    Create a tube database / add playlists or videos to an existing database

        lb tubeadd educational.db https://www.youtube.com/c/BranchEducation/videos

    Fetch extra metadata:

        By default tubeadd will quickly add media.
        You can always fetch more metadata later via tubeupdate.

        lb tubeupdate tw.db --extra
""",
    )
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

        if args.extra:
            log.warning("Getting extra metadata")
            get_extra_metadata(args, playlist)


def tube_update():
    args = parse_args(
        "update",
        usage="""usage: lb tubeupdate [--optimize] [database] [playlists ...]

    Fetch the latest videos from every playlist in your database

        lb tubeupdate educational.db

    Or limit to specific ones...

        lb tubeupdate educational.db https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos ...

    Run with --optimize to add indexes (might speed up searching but the size will increase):

        lb tubeupdate --optimize examples/music.tl.db ''

    Fetch extra metadata:

        By default tubeupdate will quickly add media.
        You can run with --extra to fetch more details: (best resolution width, height, subtitle tags, etc)

        lb tubeupdate educational.db --extra https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos
""",
    )
    known_playlists = get_playlists(args)

    for playlist in args.playlists or get_playlists(args, include_playlistless_media=False):

        if playlist not in known_playlists:
            log.warning("Skipping unknown playlist: %s", playlist)
            continue

        start = timer()
        process_playlist(args, playlist)
        end = timer()
        log.info(f"{end - start:.1f} seconds to update playlist")

        if args.extra:
            log.warning("Getting extra metadata")
            get_extra_metadata(args, playlist)

    db.optimize(args)
