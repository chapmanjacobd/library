import argparse, json, sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yt_dlp
from sqlite_utils.db import NotFoundError

from xklb import consts, fs_extract, utils
from xklb.consts import DBType
from xklb.dl_config import (
    prefix_unrecoverable_errors,
    yt_meaningless_errors,
    yt_recoverable_errors,
    yt_unrecoverable_errors,
)
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
        "noplaylist": False,
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
                "1 Hour",
                "2 Hour",
                "3 Hour",
                "4 Hour",
                "5 Hour",
                "6 Hour",
                "7 Hour",
                "8 Hour",
                "9 Hour",
                "10 Hour",
                "100 Hour",
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

    if args.verbose == 0 and not consts.PYTEST_RUNNING:
        all_opts.update(ignoreerrors="only_download")
    if args.verbose >= 2:
        all_opts.update(ignoreerrors=False, quiet=False)
    if args.ignore_errors:
        all_opts.update(ignoreerrors=True)

    log.debug(utils.dict_filter_bool(all_opts))

    if hasattr(args, "playlists") and args.playlists and hasattr(args, "no_sanitize") and not args.no_sanitize:
        args.playlists = [utils.sanitize_url(args, path) for path in args.playlists]

    return all_opts


def is_supported(url) -> bool:  # thank you @dbr
    ies = yt_dlp.extractor.gen_extractors()
    for ie in ies:
        if ie.suitable(url) and ie.IE_NAME != "generic":
            return True  # Site has dedicated extractor
    return False


def is_playlist_known(args, playlist_path) -> bool:
    try:
        known = args.db.execute("select 1 from playlists where path=?", [playlist_path]).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return True


def is_video_known(args, playlist_path, path) -> bool:
    m_columns = args.db["media"].columns_dict
    try:
        known = args.db.execute(
            f"select 1 from media where playlist_path=? and (path=? or {'web' if 'webpath' in m_columns else ''}path=?)",
            [playlist_path, path, path],
        ).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return True


def consolidate(v: dict) -> Optional[dict]:
    if v.get("title") in ("[Deleted video]", "[Private video]"):
        return None

    for k in list(v):
        if k.startswith("_") or k in consts.TUBE_IGNORE_KEYS:
            v.pop(k, None)

    release_date = v.pop("release_date", None)
    upload_date = v.pop("upload_date", None) or release_date
    if upload_date:
        try:
            upload_date = int(datetime.strptime(upload_date, "%Y%m%d").timestamp())
        except Exception:
            upload_date = None

    cv = {}
    cv["path"] = safe_unpack(v.pop("webpage_url", None), v.pop("url", None), v.pop("original_url", None))
    size_bytes = v.pop("filesize_approx", None)
    cv["size"] = 0 if not size_bytes else int(size_bytes)
    duration = v.pop("duration", None)
    cv["duration"] = 0 if not duration else int(duration)
    cv["time_uploaded"] = upload_date
    cv["time_created"] = int(datetime.now().timestamp())
    cv["time_modified"] = 0
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
    )
    cv["id"] = v.pop("id", None)
    if cv["id"] is None:
        log.warning("No id found in %s", v)
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

    return utils.dict_filter_bool(cv)


def log_problem(args, playlist_path) -> None:
    if is_playlist_known(args, playlist_path):
        log.warning("Start of known playlist reached %s", playlist_path)
    else:
        log.warning("Could not add playlist %s", playlist_path)


def _add_playlist(args, playlist_path, pl: dict, media_path: Optional[str] = None) -> None:
    extractor = safe_unpack(pl.get("ie_key"), pl.get("extractor_key"), pl.get("extractor"))
    playlist = {
        "ie_key": extractor,
        "title": pl.get("playlist_title"),
        "path": playlist_path,
        "uploader": safe_unpack(pl.get("playlist_uploader_id"), pl.get("playlist_uploader")),
        "id": pl.get("playlist_id"),
        "dl_config": args.dl_config,
        "time_deleted": 0,
        "category": args.category or extractor,
        **args.extra_playlist_data,
    }

    if not playlist.get("id") or media_path == playlist["path"]:
        log.warning("Importing playlist-less media %s", playlist["path"])
    else:
        args.db["playlists"].upsert(utils.dict_filter_bool(playlist), pk="path", alter=True)


def save_undownloadable(args, playlist_path):
    entry = {
        "path": playlist_path,
        "title": "No data from ydl.extract_info",
        "category": args.category or "Uncategorized",
        "dl_config": args.dl_config,
        **args.extra_playlist_data,
    }
    args.db["playlists"].upsert(utils.dict_filter_bool(entry), pk="path", alter=True)


playlists_of_playlists = []
added_media_count = 0


def process_playlist(args, playlist_path, ydl_opts, playlist_root=True) -> Optional[List[Dict]]:
    for k, v in args.extra_playlist_data.items():
        setattr(args, k, v)

    class ExistingPlaylistVideoReached(yt_dlp.DownloadCancelled):
        pass

    class AddToArchivePP(yt_dlp.postprocessor.PostProcessor):
        def run(self, info) -> Tuple[list, dict]:  # pylint: disable=arguments-renamed
            global added_media_count

            if info:
                url = safe_unpack(info.get("webpage_url"), info.get("url"), info.get("original_url"))
                if url != playlist_path and info.get("webpage_url_basename") == "playlist":
                    if playlist_root:
                        _add_playlist(args, playlist_path, deepcopy(info))

                    if args.ignore_errors:
                        if url in playlists_of_playlists and not playlist_root:
                            raise ExistingPlaylistVideoReached  # prevent infinite bug
                    else:
                        if url in playlists_of_playlists:
                            raise ExistingPlaylistVideoReached  # prevent infinite bug

                    process_playlist(args, url, ydl_opts, playlist_root=False)
                    playlists_of_playlists.append(url)
                    return [], info

                entry = consolidate(deepcopy(info))
                if entry:
                    entry["playlist_path"] = playlist_path
                    _add_playlist(args, playlist_path, deepcopy(info), entry["path"])

                    if is_video_known(args, playlist_path, entry["path"]) and not args.ignore_errors:
                        raise ExistingPlaylistVideoReached

                    entry = {**entry, **args.extra_media_data}
                    args.db["media"].upsert(utils.dict_filter_bool(entry), pk="path", alter=True)

                    added_media_count += 1
                    if added_media_count > 1:
                        sys.stdout.write("\033[K\r")
                        print(f"[{playlist_path}] Added {added_media_count} media", end="\r", flush=True)

            return [], info

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.add_post_processor(AddToArchivePP(), when="pre_process")

        count_before_extract = added_media_count
        try:
            pl = ydl.extract_info(playlist_path, download=False, process=True)
        except ExistingPlaylistVideoReached:
            if added_media_count > count_before_extract:
                sys.stdout.write("\n")
            log_problem(args, playlist_path)
        else:
            if added_media_count > count_before_extract:
                sys.stdout.write("\n")
            if not pl and not args.safe:
                log.warning("Logging undownloadable media")
                save_undownloadable(args, playlist_path)


def get_extra_metadata(args, playlist_path, playlist_dl_opts=None) -> Optional[List[Dict]]:
    m_columns = args.db["media"].columns_dict

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
            f"""
            SELECT
                path
            , ie_key
            , play_count
            , time_played
            FROM media
            WHERE 1=1
                {'and width is null' if 'width' in m_columns else ''}
                and path not like '%playlist%'
                and playlist_path = ?
            ORDER by random()
            """,
            [playlist_path],
        ).fetchall()

        current_video_count = 0
        for path, ie_key, play_count, time_played in videos:
            entry = ydl.extract_info(path, ie_key=ie_key, download=False)
            if entry is None:
                continue

            entry = consolidate(entry)
            if entry is None:
                continue

            entry["playlist_path"] = playlist_path
            entry["play_count"] = play_count
            entry["time_played"] = time_played
            args.db["media"].upsert(utils.dict_filter_bool(entry), pk="path", alter=True)

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
            tube_opts(args, playlist_opts=d.get("dl_config", "{}"), func_opts={"ignoreerrors": "only_download"}),
        )

        if args.extra:
            log.warning("[%s]: Getting extra metadata", d["path"])
            get_extra_metadata(args, d["path"], playlist_dl_opts=d.get("dl_config", "{}"))


def save_tube_entry(args, m, info: Optional[dict] = None, error=None, URE=False) -> None:
    webpath = m["path"]

    v_id = m.get("id")
    if v_id:
        error = None if not error else error.replace(v_id, "").replace(" :", ":")

    if not info:  # not downloaded or already downloaded
        entry = {
            "path": webpath,
            "time_downloaded": 0,
            "time_modified": consts.NOW,
            "time_deleted": consts.NOW if URE else 0,
            "error": error,
        }
        args.db["media"].upsert(utils.dict_filter_bool(entry), pk="path", alter=True)  # type: ignore
        return

    assert info["local_path"] != ""
    if Path(info["local_path"]).exists():
        fs_args = argparse.Namespace(
            profile=args.profile,
            scan_subtitles=True if args.profile == DBType.video else False,
            delete_unplayable=False,
            ocr=False,
            speech_recognition=False,
        )
        fs_tags = utils.dict_filter_bool(fs_extract.extract_metadata(fs_args, info["local_path"]), keep_0=False) or {}
        for p in Path(consts.SUB_TEMP_DIR).glob("*.srt"):
            p.unlink()
    else:
        fs_tags = {}

    tube_entry = consolidate(info) or {}
    tube_entry.pop("play_count", None)
    tube_entry.pop("time_played", None)

    entry = {
        **tube_entry,
        **fs_tags,
        "webpath": webpath,
        "time_modified": consts.NOW,
        "time_downloaded": 0 if error else consts.NOW,
        "time_deleted": consts.NOW if URE else 0,
        "error": error,
    }
    args.db["media"].upsert(utils.dict_filter_bool(entry), pk="path", alter=True)  # type: ignore

    if fs_tags:
        try:
            args.db["media"].delete(webpath)
        except NotFoundError:
            pass


def yt(args, m) -> None:
    if not m["path"].startswith("http"):
        return

    ydl_log = {"warning": [], "error": [], "info": []}

    class BadToTheBoneLogger:
        def debug(self, msg):
            if msg.startswith("[debug] "):
                pass
            else:
                self.info(msg)

        def info(self, msg):
            ydl_log["info"].append(msg)

        def warning(self, msg):
            ydl_log["warning"].append(msg)

        def error(self, msg):
            ydl_log["error"].append(msg)

    ignoreerrors = False
    if m.get("time_modified") and m.get("time_modified") > 0:
        ignoreerrors = True

    out_dir = lambda p: str(Path(args.prefix, m["category"] or "%(extractor_key,extractor)s", p))
    ydl_opts = tube_opts(
        args,
        func_opts={
            "ignoreerrors": ignoreerrors,
            "subtitleslangs": ["en.*", "EN.*"],
            "extractor_args": {"youtube": {"skip": ["authcheck"]}},
            "logger": BadToTheBoneLogger(),
            "writesubtitles": True,
            "writeautomaticsub": True,
            "skip_download": True if consts.PYTEST_RUNNING else False,
            "subtitlesformat": "srt/best",
            "extract_flat": False,
            "lazy_playlist": False,
            "postprocessors": [{"key": "FFmpegMetadata"}, {"key": "FFmpegEmbedSubtitle"}],
            "restrictfilenames": True,
            "extractor_retries": 13,
            "retries": 13,
            "outtmpl": {
                "default": out_dir("%(uploader,uploader_id)s/%(title).200B_[%(id).60B].%(ext)s"),
                "chapter": out_dir(
                    "%(uploader,uploader_id)s/%(title).200B_%(section_number)03d_%(section_title)s_[%(id).60B].%(ext)s"
                ),
            },
        },
        playlist_opts=m.get("dl_config", "{}"),
    )

    download_archive = Path(args.download_archive).expanduser().resolve()
    if download_archive.exists():
        ydl_opts["download_archive"] = str(download_archive)
        ydl_opts["cookiesfrombrowser"] = ("firefox",)

    if args.small:
        ydl_opts["format"] = "bestvideo[height<=576]+bestaudio/best[height<=576]/best"

    if args.ext == "DEFAULT":
        if args.profile == DBType.audio:
            args.ext = "opus"
        else:
            args.ext = None

    if args.profile == DBType.audio:
        ydl_opts[
            "format"
        ] = "bestaudio[ext=opus]/bestaudio[ext=webm]/bestaudio[ext=ogg]/bestaudio[ext=oga]/bestaudio/best"
        ydl_opts["postprocessors"].append({"key": "FFmpegExtractAudio", "preferredcodec": args.ext})

    match_filters = ["live_status=?not_live"]
    if args.small:
        match_filters.append("duration >? 59 & duration <? 14399")
    match_filter_user_config = ydl_opts.get("match_filter")
    if match_filter_user_config is not None:
        match_filters.append(match_filter_user_config)
    ydl_opts["match_filter"] = yt_dlp.utils.match_filter_func(" & ".join(match_filters).split(" | "))

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(m["path"], download=True)
        except yt_dlp.DownloadError as e:
            error = consts.REGEX_ANSI_ESCAPE.sub("", str(e))
            ydl_log["error"].append(error)
            info = None
            log.debug("[%s]: yt-dlp %s", m["path"], error)
            # save_tube_entry(args, m, error=error)
            # return

        if info is None:
            log.debug("[%s]: yt-dlp returned no info", m["path"])
        else:
            if args.profile == DBType.audio:
                info["local_path"] = ydl.prepare_filename({**info, "ext": args.ext})
            else:
                info["local_path"] = ydl.prepare_filename(info)

        ydl_errors = ydl_log["error"] + ydl_log["warning"]
        ydl_errors = "\n".join([l for l in ydl_errors if not yt_meaningless_errors.match(l)])
        ydl_full_log = ydl_log["error"] + ydl_log["warning"] + ydl_log["info"]

        if not ydl_log["error"] and info:
            log.debug("[%s]: No news is good news", m["path"])
            save_tube_entry(args, m, info)
        elif any([yt_recoverable_errors.match(l) for l in ydl_full_log]):
            log.info("[%s]: Recoverable error matched (will try again later). %s", m["path"], ydl_errors)
            save_tube_entry(args, m, info, error=ydl_errors)
        elif any([yt_unrecoverable_errors.match(l) for l in ydl_full_log]):
            matched_error = [m.string for m in utils.conform([yt_unrecoverable_errors.match(l) for l in ydl_full_log])]
            log.debug("[%s]: Unrecoverable error matched. %s", m["path"], ydl_errors or utils.combine(matched_error))
            save_tube_entry(args, m, info, error=ydl_errors, URE=True)
        elif any([prefix_unrecoverable_errors.match(l) for l in ydl_full_log]):
            log.warning("[%s]: Prefix error. %s", m["path"], ydl_errors)
            raise SystemExit(28)
        else:
            if ydl_errors != "":
                log.error("[%s]: Unknown error. %s", m["path"], ydl_errors)
            save_tube_entry(args, m, info, error=ydl_errors)
