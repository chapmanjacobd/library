import json, sqlite3, sys, tempfile
from copy import deepcopy
from datetime import datetime
from sqlite3 import OperationalError
from time import sleep
from typing import Dict, List, Optional, Tuple, Union
from urllib.error import HTTPError

import yt_dlp

from xklb import consts, utils
from xklb.consts import SUB_TEMP_DIR
from xklb.subtitle import subs_to_text
from xklb.utils import combine, log, safe_unpack


def tube_opts(args, func_opts=None, playlist_opts: Optional[str] = None) -> dict:
    if playlist_opts is None or playlist_opts == "":
        playlist_opts = "{}"
    if func_opts is None:
        func_opts = {}
    cli_opts = {}
    if hasattr(args, "dl_config"):
        cli_opts = args.dl_config

    default_opts = {
        "ignoreerrors": False,
        "no_warnings": False,
        "quiet": True,
        "noprogress": True,
        "skip_download": True,
        "lazy_playlist": True,
        "extract_flat": True,
        "dynamic_mpd": False,
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,
        "no_check_certificate": True,
        "check_formats": False,
        "ignore_no_formats_error": True,
        "skip_playlist_after_errors": 21,
        "clean_infojson": False,
        "playlistend": 20000,
        "rejecttitle": "|".join(
            [
                " AWARD",
                " Clip",
                " GPU ",
                " Scene",
                " Terror",
                "360",
                "Advert",
                "Announcement",
                "Apology",
                "Best of",
                "Bitcoin",
                "campaign",
                "Ceremony",
                "Clip ",
                "Compilation",
                "Crypto ",
                "Event",
                "Final Look",
                "First Look",
                "Graphics Card",
                "Horror",
                "In Theaters",
                "Live ",
                "Makeup",
                "Meetup",
                "Montage",
                "Now Playing",
                "Outtakes",
                "Panel",
                "Preview",
                "Promo",
                "Red Carpet Premiere",
                "Sneak Peek",
                "Stream",
                "Teaser",
                "Top 10",
                "Top 2",
                "Top 3",
                "Top 4",
                "Top 5",
                "Top 6",
                "Top 7",
                "Top 8",
                "Top 9",
                "Top Eight",
                "Top Five",
                "Top Four",
                "Top Nine",
                "Top Seven",
                "Top Six",
                "Top Ten",
                "Top Three",
                "Top Two",
                "Trailer",
                "TV Spot",
                "Twitch",
                "World Premiere",
            ]
        ),
    }

    all_opts = {
        **default_opts,
        **func_opts,
        **json.loads(playlist_opts),
        **cli_opts,
    }

    if args.verbose == 0 and not utils.PYTEST_RUNNING:
        all_opts.update(ignoreerrors="only_download")
    if args.verbose >= 2:
        all_opts.update(ignoreerrors=False, quiet=False)
    if args.ignore_errors:
        all_opts.update(ignoreerrors=True)

    log.debug(utils.dict_filter_bool(all_opts))

    if hasattr(args, "playlists") and args.playlists and not args.no_sanitize:
        args.playlists = [consts.sanitize_url(args, path) for path in args.playlists]

    return all_opts


def is_supported(url) -> bool:  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def get_playlists(args, cols="path, dl_config", constrain=False) -> List[dict]:
    columns = args.db["playlists"].columns
    sql_filters = []
    if "time_deleted" in columns:
        sql_filters.append("AND time_deleted=0")
    if constrain:
        if args.category:
            sql_filters.append(f"AND category='{args.category}'")
        if args.profile:
            sql_filters.append(f"AND profile='{args.profile}'")

    try:
        known_playlists = list(
            args.db.query(f"select {cols} from playlists where 1=1 {' '.join(sql_filters)} order by random()")
        )
    except OperationalError:
        known_playlists = []
    return known_playlists


def is_playlist_known(args, playlist_path) -> bool:
    try:
        known = args.db.execute("select 1 from playlists where path=?", [playlist_path]).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return known[0]


def is_video_known(args, playlist_path, path) -> bool:
    try:
        known = args.db.execute(
            "select 1 from media where playlist_path=? and path=?", [playlist_path, path]
        ).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return known[0]


def _get_existing_row(args, table, path) -> dict:
    try:
        r = list(args.db.query(f"select * from {table} where path=?", [path]))
    except sqlite3.OperationalError:
        return {}
    if len(r) == 1:
        return r[0]
    return {}


def get_subtitle_text(ydl: yt_dlp.YoutubeDL, video_path, req_sub_dict) -> str:
    def dl_sub(url):
        temp_file = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)

        try:
            ydl.dl(temp_file, {"url": url}, subtitle=True)
        except HTTPError:
            log.info("Unable to download subtitles; skipping")
            sleep(5)
            return None

        return temp_file

    urls = [d["url"] for d in list(req_sub_dict.values())]
    paths = utils.conform([dl_sub(url) for url in urls])

    subs_text = subs_to_text(video_path, paths)
    for p in paths:
        utils.trash(p)

    return subs_text


def consolidate(playlist_path: str, v: dict, ydl: Optional[yt_dlp.YoutubeDL] = None) -> Union[dict, None]:
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
        "requested_downloads",
        "thumbnails",
        "playlist_count",
        "playlist_id",
        "playlist_title",
        "playlist_uploader",
        "audio_channels",
        "subtitles",
        "automatic_captions",
        "quality",
        "has_drm",
        "language_preference",
        "preference",
        "location",
        "downloader_options",
        "container",
        "local_path",
        "album",
        "artist",
        "release_year",
        "creator",
        "alt_title",
    ]

    if v.get("title") in ("[Deleted video]", "[Private video]"):
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
        if ydl:
            subtitles = get_subtitle_text(ydl, playlist_path, subtitles)
        else:
            subtitles = None

    cv = {}
    cv["path"] = safe_unpack(v.pop("webpage_url", None), v.pop("url", None), v.pop("original_url", None))
    size_bytes = v.pop("filesize_approx", None)
    cv["size"] = 0 if not size_bytes else int(size_bytes)
    duration = v.pop("duration", None)
    cv["duration"] = 0 if not duration else int(duration)
    cv["time_uploaded"] = upload_date
    cv["time_created"] = int(datetime.now().timestamp())
    cv["time_deleted"] = 0
    cv["time_downloaded"] = 0
    cv["play_count"] = 0
    cv["time_played"] = 0
    language = v.pop("language", None)
    cv["tags"] = combine(
        "language:" + language if language else None,
        v.pop("description", None),
        v.pop("categories", None),
        v.pop("tags", None),
        subtitles,
    )
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
        v.pop("playlist_uploader_id", None),
        v.pop("channel_id", None),
        v.pop("playlist_uploader", None),
        v.pop("uploader_url", None),
        v.pop("channel_url", None),
        v.pop("uploader", None),
        v.pop("channel", None),
        v.pop("uploader_id", None),
    )

    if v != {}:
        log.info("Extra data %s", v)
        # breakpoint()

    return cv


def save_entries(args, entries) -> None:
    if entries:
        args.db["media"].insert_all(entries, pk="path", alter=True, replace=True)  # type: ignore


def log_problem(args, playlist_path) -> None:
    if is_playlist_known(args, playlist_path):
        log.warning("Start of known playlist reached %s", playlist_path)
    else:
        log.warning("Could not add playlist %s", playlist_path)


def _add_playlist(args, playlist_path, pl: dict, media_path: Optional[str] = None) -> None:
    pl = dict(
        ie_key=safe_unpack(pl.get("ie_key"), pl.get("extractor_key"), pl.get("extractor")),
        title=pl.get("playlist_title"),
        path=playlist_path,
        uploader=safe_unpack(pl.get("playlist_uploader_id"), pl.get("playlist_uploader")),
        id=pl.get("playlist_id"),
        dl_config=args.dl_config,
        time_deleted=0,
        category=None,
        profile=None,
    )
    if not pl.get("id") or media_path == pl["path"]:
        log.warning("Importing playlist-less media %s", pl["path"])
    else:
        existing_data = _get_existing_row(args, "playlists", playlist_path)
        args.db["playlists"].insert(
            {**pl, **existing_data, **args.extra_playlist_data}, pk="path", alter=True, replace=True
        )


playlists_of_playlists = []
added_media_count = 0


def process_playlist(args, playlist_path, ydl_opts, playlist_root=True) -> Union[List[Dict], None]:
    class ExistingPlaylistVideoReached(yt_dlp.DownloadCancelled):
        pass

    class AddToArchivePP(yt_dlp.postprocessor.PostProcessor):
        def run(self, info) -> Tuple[list, dict]:  # pylint: disable=arguments-renamed
            global added_media_count

            if info:
                url = safe_unpack(info.get("webpage_url"), info.get("url"), info.get("original_url"))
                if url != playlist_path and info.get("webpage_url_basename") == "playlist":
                    if url in playlists_of_playlists:
                        raise ExistingPlaylistVideoReached  # prevent infinite bug

                    process_playlist(args, url, ydl_opts, playlist_root=False)
                    playlists_of_playlists.append(url)
                    if playlist_root:
                        _add_playlist(args, playlist_path, deepcopy(info))
                    return [], info

                entry = consolidate(playlist_path, deepcopy(info), ydl=super)  # type: ignore
                if entry:
                    if is_video_known(args, playlist_path, entry["path"]):
                        raise ExistingPlaylistVideoReached
                    save_entries(args, [{**entry, **args.extra_media_data}])
                    _add_playlist(args, playlist_path, deepcopy(info), entry["path"])

                    added_media_count += 1
                    if added_media_count > 1:
                        sys.stdout.write("\033[K\r")
                        print(f"[{playlist_path}] Added {added_media_count} media", end="\r", flush=True)

            return [], info

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.add_post_processor(AddToArchivePP(), when="pre_process")

        try:
            pl = ydl.extract_info(playlist_path, download=False, process=True)
        except ExistingPlaylistVideoReached:
            log_problem(args, playlist_path)
        else:
            sys.stdout.write("\n")
            if not pl:
                log.warning("Logging undownloadable media")
                existing_data = _get_existing_row(args, "undownloadable", playlist_path)
                args.db["undownloadable"].insert(
                    {
                        "path": playlist_path,
                        "category": None,
                        "profile": None,
                        "dl_config": args.dl_config,
                        **existing_data,
                        **args.extra_playlist_data,
                    },
                    pk="path",
                    alter=True,
                    replace=True,
                )


def get_extra_metadata(args, playlist_path, playlist_dl_opts=None) -> Union[List[Dict], None]:
    with yt_dlp.YoutubeDL(
        tube_opts(
            args,
            func_opts={
                "subtitlesformat": "srt/best",
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en.*", "EN.*"],
                "extract_flat": False,
                "lazy_playlist": False,
                "skip_download": True,
                "check_formats": False,
                "ignoreerrors": True,
            },
            playlist_opts=playlist_dl_opts,
        )
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

            entry = consolidate(playlist_path, entry, ydl)
            if entry is None:
                continue

            entry["play_count"] = play_count
            entry["time_played"] = time_played

            save_entries(args, [entry])

            current_video_count += 1
            sys.stdout.write("\033[K\r")
            print(
                f"[{playlist_path}] {current_video_count} of {len(videos)} extra metadata fetched", end="\r", flush=True
            )


def update_playlists(args, playlists):
    for d in playlists:
        process_playlist(
            args,
            d["path"],
            tube_opts(args, playlist_opts=d["dl_config"], func_opts={"ignoreerrors": "only_download"}),
        )

        if args.extra:
            log.warning("[%s]: Getting extra metadata", d["path"])
            get_extra_metadata(args, d["path"], playlist_dl_opts=d["dl_config"])
