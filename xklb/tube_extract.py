import argparse, json, sqlite3, sys, tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from sqlite3 import OperationalError
from time import sleep
from typing import Dict, List, Optional, Tuple, Union
from urllib.error import HTTPError

import yt_dlp

from xklb import db, tube_actions, utils
from xklb.paths import SUB_TEMP_DIR
from xklb.subtitle import subs_to_text
from xklb.utils import combine, log, safe_unpack


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library tube" + action, usage=usage)
    parser.add_argument("database", nargs="?", default="tube.db")
    if action == "add":
        parser.add_argument("playlists", nargs="+")
    elif action == "update":
        parser.add_argument("playlists", nargs="*")
        parser.add_argument("--optimize", action="store_true", help="Optimize Database")

    parser.add_argument(
        "--dl-config",
        "-dl-config",
        nargs=1,
        action=utils.argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default downloader configuration",
    )
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters")

    parser.add_argument("--extra", "-extra", action="store_true", help="Get full metadata (takes a lot longer)")

    parser.add_argument("--extra-media-data", default={})
    parser.add_argument("--extra-playlist-data", default={})
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def is_supported(url) -> bool:  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def get_subtitle_text(ydl: yt_dlp.YoutubeDL, video_path, req_sub_dict) -> str:
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
    [utils.trash(p) for p in paths]

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
        if ydl:
            subtitles = get_subtitle_text(ydl, playlist_path, subtitles)
        else:
            subtitles = None

    cv = dict()
    cv["path"] = safe_unpack(v.pop("webpage_url", None), v.pop("url", None), v.pop("original_url", None))
    size_bytes = v.pop("filesize_approx", None)
    cv["size"] = 0 if not size_bytes else int(size_bytes)
    cv["time_created"] = upload_date
    duration = v.pop("duration", None)
    cv["duration"] = 0 if not duration else int(duration)
    cv["is_deleted"] = 0
    cv["is_downloaded"] = 0
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


def save_entries(args, entries) -> None:
    if entries:
        args.db["media"].insert_all(entries, pk="path", alter=True, replace=True)  # type: ignore


def log_problem(args, playlist_path) -> None:
    if is_playlist_known(args, playlist_path):
        log.warning("Start of known playlist reached %s", playlist_path)
    else:
        log.warning("Could not add playlist %s", playlist_path)


def process_playlist(args, playlist_path, ydl_opts) -> Union[List[Dict], None]:
    class ExistingPlaylistVideoReached(yt_dlp.DownloadCancelled):
        pass

    class AddToArchivePP(yt_dlp.postprocessor.PostProcessor):
        current_video_count = 0

        def run(self, info) -> Tuple[list, dict]:
            if info:
                entry = self._add_media(deepcopy(info))
                if entry:
                    self._add_playlist(deepcopy(info), entry)

                    self.current_video_count += 1
                    sys.stdout.write("\033[K\r")
                    print(f"[{playlist_path}] Added {self.current_video_count} videos", end="\r", flush=True)
            return [], info

        def _add_media(self, entry) -> Union[dict, None]:
            entry = consolidate(playlist_path, entry, ydl=super)  # type: ignore
            if entry:
                if self.current_video_count >= 1 and is_video_known(args, playlist_path, entry["path"]):
                    raise ExistingPlaylistVideoReached
                save_entries(args, [{**entry, **args.extra_media_data}])
            return entry

        def _add_playlist(self, pl: dict, entry: dict) -> None:
            pl = dict(
                ie_key=safe_unpack(pl.get("ie_key"), pl.get("extractor_key"), pl.get("extractor")),
                title=pl.get("playlist_title"),
                path=playlist_path,
                uploader=safe_unpack(pl.get("playlist_uploader_id"), pl.get("playlist_uploader")),
                id=pl.get("playlist_id"),
                dl_config=args.dl_config,
                is_deleted=0,
                category=None,
                profile=None,
            )
            if entry["path"] == pl["path"] or not pl.get("id"):
                log.warning("Importing playlist-less media %s", pl["path"])
            else:
                existing_data = self._get_existing_playlist()
                args.db["playlists"].insert(
                    {**pl, **existing_data, **args.extra_playlist_data}, pk="path", alter=True, replace=True
                )

        def _get_existing_playlist(self) -> dict:
            try:
                r = list(args.db.query(f"select * from playlists where path=?", [playlist_path]))
            except sqlite3.OperationalError:
                return {}
            if len(r) == 1:
                return r[0]
            return {}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.add_post_processor(AddToArchivePP(), when="pre_process")

        try:
            pl = ydl.extract_info(playlist_path, download=False, process=True)
        except ExistingPlaylistVideoReached:
            log_problem(args, playlist_path)
        else:
            if not pl:
                log_problem(args, playlist_path)


def get_extra_metadata(args, playlist_path, playlist_dl_opts) -> Union[List[Dict], None]:
    with yt_dlp.YoutubeDL(
        tube_actions.ydl_opts(
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


def get_playlists(args, cols="path, dl_config", constrain=False) -> List[dict]:
    columns = args.db["playlists"].columns
    sql_filters = []
    if "is_deleted" in columns:
        sql_filters.append("AND is_deleted=0")
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


def get_playlist_dl_config(playlists, path):
    for d in playlists:
        if d["path"] == path:
            return json.loads(d["dl_config"])


def tube_add(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        "add",
        usage="""library tubeadd [database] playlists ...

    Create a tube database / add playlists or videos to an existing database

        library tubeadd educational.db https://www.youtube.com/c/BranchEducation/videos

    Fetch extra metadata:

        By default tubeadd will quickly add media.
        You can always fetch more metadata later via tubeupdate.

        library tubeupdate tw.db --extra
""",
    )
    playlists = get_playlists(args)
    for path in args.playlists:
        playlist_dl_config = get_playlist_dl_config(playlists, path)
        if playlist_dl_config:
            log.info("[%s]: Updating known playlist", path)

        if args.safe and not is_supported(path):
            log.warning("[%s]: Unsupported playlist (safe_mode)", path)
            continue

        process_playlist(args, path, playlist_dl_config)

        if args.extra:
            log.warning("[%s]: Getting extra metadata", path)
            get_extra_metadata(args, path, playlist_dl_config)


def update_playlists(args, playlists):
    playlists = [
        {**d, "dl_config": json.loads(d["dl_config"])}
        for d in playlists
        if not args.playlists or d["path"] in args.playlists
    ]
    for d in playlists:
        process_playlist(args, d["path"], tube_actions.ydl_opts(args, playlist_opts=d["dl_config"]))

        if args.extra:
            log.warning("[%s]: Getting extra metadata", d["path"])
            get_extra_metadata(args, d["path"], tube_actions.ydl_opts(args, playlist_opts=d["dl_config"]))


def show_unknown_playlist_warning(args, playlists, sc_name="tubeadd"):
    known_playlists = [p["path"] for p in playlists]
    for p in args.playlists:
        if p not in known_playlists:
            log.warning("[%s]: Skipping unknown playlist. Add new playlists with %s", p, sc_name)


def tube_update(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        "update",
        usage="""usage: library tubeupdate [--optimize] [database] [playlists ...]

    Fetch the latest videos from every playlist in your database

        library tubeupdate educational.db

    Or limit to specific ones...

        library tubeupdate educational.db https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos ...

    Run with --optimize to add indexes (might speed up searching but the size will increase):

        library tubeupdate --optimize examples/music.tl.db ''

    Fetch extra metadata:

        By default tubeupdate will quickly add media.
        You can run with --extra to fetch more details: (best resolution width, height, subtitle tags, etc)

        library tubeupdate educational.db --extra https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos
""",
    )
    playlists = get_playlists(args)
    show_unknown_playlist_warning(args, playlists)

    update_playlists(args, playlists)

    db.optimize(args)
