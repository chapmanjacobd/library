import json, sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Tuple

from xklb import db_media, db_playlists
from xklb.data.dl_config import (
    prefix_unrecoverable_errors,
    yt_meaningless_errors,
    yt_recoverable_errors,
    yt_unrecoverable_errors,
)
from xklb.media import subtitle
from xklb.utils import consts, db_utils, iterables, objects, path_utils, printing, sql_utils, strings
from xklb.utils.consts import DBType
from xklb.utils.log_utils import Timer, log

yt_dlp = None
yt_archive = set()


def load_module_level_yt_dlp() -> ModuleType:
    global yt_dlp

    if yt_dlp is None:
        import yt_dlp
    return yt_dlp


def tube_opts(args, func_opts=None, playlist_opts: Optional[str] = None) -> dict:
    if playlist_opts is None or playlist_opts == "":
        playlist_opts = "{}"
    if func_opts is None:
        func_opts = {}
    cli_opts = {}
    if hasattr(args, "extractor_config"):
        cli_opts = args.extractor_config

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
    }

    all_opts = {
        **default_opts,
        **func_opts,
        **json.loads(playlist_opts),
        **cli_opts,
    }

    if args.verbose == 0 and not consts.PYTEST_RUNNING:
        all_opts.update(ignoreerrors="only_download")
    if args.verbose >= consts.LOG_DEBUG:
        all_opts.update(ignoreerrors=False, quiet=False)
    if args.ignore_errors:
        all_opts.update(ignoreerrors=True)

    log.debug(objects.dict_filter_bool(all_opts))

    if hasattr(args, "playlists") and args.playlists and hasattr(args, "no_sanitize") and not args.no_sanitize:
        args.playlists = [path_utils.sanitize_url(args, path) for path in args.playlists]

    return all_opts


def is_supported(url) -> bool:  # thank you @dbr
    if consts.REGEX_V_REDD_IT.match(url):
        return True

    if getattr(is_supported, "yt_ies", None) is None:
        yt_dlp = load_module_level_yt_dlp()
        is_supported.yt_ies = yt_dlp.extractor.gen_extractors()

    return any(ie.suitable(url) and ie.IE_NAME != "generic" for ie in is_supported.yt_ies)


playlists_of_playlists = set()
added_media_count = 0


def get_playlist_metadata(args, playlist_path, ydl_opts, playlist_root=True) -> None:
    yt_dlp = load_module_level_yt_dlp()
    t = Timer()

    class ExistingPlaylistVideoReached(yt_dlp.DownloadCancelled):
        pass

    class AddToArchivePP(yt_dlp.postprocessor.PostProcessor):
        def run(self, info) -> Tuple[list, dict]:  # pylint: disable=arguments-renamed
            global added_media_count

            if info:
                webpath = iterables.safe_unpack(info.get("webpage_url"), info.get("url"), info.get("original_url"))
                extractor_key = "ydl_" + (
                    iterables.safe_unpack(info.get("ie_key"), info.get("extractor_key"), info.get("extractor")) or ""
                )

                if webpath != playlist_path and info.get("webpage_url_basename") == "playlist":
                    if playlist_root:
                        if not info.get("playlist_id") or webpath == playlist_path:
                            log.warning("Importing playlist-less media %s", playlist_path)
                        db_playlists.add(args, playlist_path, info, extractor_key=extractor_key)
                        log.info("playlists.add %s", t.elapsed())

                    if args.ignore_errors:
                        if webpath in playlists_of_playlists and not playlist_root:
                            raise ExistingPlaylistVideoReached  # prevent infinite bug
                    else:
                        if webpath in playlists_of_playlists:
                            raise ExistingPlaylistVideoReached  # prevent infinite bug

                    get_playlist_metadata(args, webpath, ydl_opts, playlist_root=False)
                    log.info("get_playlist_metadata %s", t.elapsed())
                    playlists_of_playlists.add(webpath)
                    return [], info

                entry = objects.dumbcopy(info)
                if entry:
                    if db_playlists.media_exists(args, playlist_path, webpath) and not args.ignore_errors:
                        raise ExistingPlaylistVideoReached

                    entry = {**entry, **args.extra_media_data}

                    if not info.get("playlist_id") or webpath == playlist_path:
                        log.warning("Importing playlist-less media %s", playlist_path)
                    else:
                        # add sub-playlist
                        playlist_id = db_playlists.add(args, playlist_path, info, extractor_key=extractor_key)
                        entry["playlist_id"] = playlist_id
                        log.info("playlists.add2 %s", t.elapsed())

                    db_media.playlist_media_add(args, webpath, entry)  # type: ignore
                    log.info("media.playlist_media_add %s", t.elapsed())

                    added_media_count += 1
                    if added_media_count > 1:
                        printing.print_overwrite(f"[{playlist_path}] Added {added_media_count} media")

            return [], info

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.add_post_processor(AddToArchivePP(), when="pre_process")

        log.info("yt-dlp initialized %s", t.elapsed())
        count_before_extract = added_media_count
        try:
            pl = ydl.extract_info(playlist_path, download=False, process=True)
            log.info("ydl.extract_info done %s", t.elapsed())
        except yt_dlp.DownloadError:
            log.error("[%s] DownloadError skipping", playlist_path)
            return
        except ExistingPlaylistVideoReached:
            db_playlists.log_problem(args, playlist_path)
        else:
            if not pl and not args.safe:
                log.warning("Logging undownloadable media")
                db_playlists.save_undownloadable(args, playlist_path, "video")

        if added_media_count > count_before_extract:
            sys.stdout.write("\n")

        if args.action == consts.SC.tubeupdate:
            if added_media_count > count_before_extract:
                db_playlists.decrease_update_delay(args, playlist_path)
            else:
                db_playlists.increase_update_delay(args, playlist_path)


def get_extra_metadata(args, playlist_path, playlist_dl_opts=None) -> Optional[List[Dict]]:
    yt_dlp = load_module_level_yt_dlp()

    m_columns = db_utils.columns(args, "media")

    with yt_dlp.YoutubeDL(
        tube_opts(
            args,
            func_opts={
                "subtitlesformat": "srt/best",
                "writesubtitles": args.subs,
                "writeautomaticsub": args.auto_subs,
                "subtitleslangs": args.subtitle_languages,
                "extract_flat": False,
                "lazy_playlist": False,
                "check_formats": False,
                "skip_download": True,
                "outtmpl": {
                    "default": str(
                        Path(f"{consts.SUB_TEMP_DIR}/%(uploader,uploader_id)s/%(title).200B_[%(id).60B].%(ext)s"),
                    ),
                },
                "ignoreerrors": True,
            },
            playlist_opts=playlist_dl_opts,
        ),
    ) as ydl:
        videos = args.db.execute(
            f"""
            SELECT
              id
            , path
            , playlist_id
            FROM media
            WHERE 1=1
                AND COALESCE(time_deleted, 0)=0
                {'and width is null' if 'width' in m_columns else ''}
                and path not like '%playlist%'
                and playlist_id = (select id from playlists where path = ?)
            ORDER by random()
            """,
            [playlist_path],
        ).fetchall()

        current_video_count = 0
        for id, path, playlist_id in videos:
            entry = ydl.extract_info(path)
            if entry is None:
                continue

            chapters = getattr(entry, "chapters", [])
            chapter_count = len(chapters)
            if chapter_count > 0:
                chapters = [
                    {"media_id": id, "time": int(float(d["start_time"])), "text": d.get("title")}
                    for d in chapters
                    if d.get("title") and not strings.is_generic_title(d)
                ]
                if len(chapters) > 0:
                    args.db["captions"].insert_all(chapters, alter=True)

            if entry["requested_subtitles"]:
                downloaded_subtitles = [d["filepath"] for d in entry["requested_subtitles"].values()]

                captions = []
                for subtitle_path in downloaded_subtitles:
                    try:
                        file_captions = subtitle.read_sub(subtitle_path)
                    except UnicodeDecodeError:
                        log.warning(f"[{path}] Could not decode subtitle {subtitle_path}")
                    else:
                        captions.extend([{"media_id": id, **d} for d in file_captions])
                if len(captions) > 0:
                    args.db["captions"].insert_all(captions, alter=True)

            entry["id"] = id
            entry["playlist_id"] = playlist_id
            entry["chapter_count"] = chapter_count

            db_media.playlist_media_add(args, path, entry)

            current_video_count += 1
            printing.print_overwrite(f"[{playlist_path}] {current_video_count} of {len(videos)} extra metadata fetched")


def get_video_metadata(args, playlist_path) -> Optional[Dict]:
    yt_dlp = load_module_level_yt_dlp()

    with yt_dlp.YoutubeDL(
        tube_opts(
            args,
            func_opts={
                "skip_download": True,
                "extract_flat": True,
                "lazy_playlist": True,
                "check_formats": False,
                "ignoreerrors": False,
                "playlistend": ":1",
                "noplaylist": True,
            },
        ),
    ) as ydl:
        entry = ydl.extract_info(playlist_path, download=False)
        if entry and "entries" in entry:
            entries = entry.pop("entries")[0]
            entry = {**entry, **entries}
        return entry


def download(args, m) -> None:
    yt_dlp = load_module_level_yt_dlp()

    ydl_log = {"error": [], "warning": [], "info": []}

    class DictLogger:
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

    def out_dir(p):
        return str(Path(args.prefix, "%(extractor_key,extractor)s", p))

    func_opts = {
        "ignoreerrors": ignoreerrors,
        "extractor_args": {"youtube": {"skip": ["authcheck"]}},
        "logger": DictLogger(),
        "skip_download": bool(consts.PYTEST_RUNNING),
        "postprocessors": [{"key": "FFmpegMetadata"}],
        "restrictfilenames": True,
        "extract_flat": False,
        "lazy_playlist": True,
        "noplaylist": True,
        "playlist_items": "1",
        "playlist_end": None,
        "extractor_retries": 3,
        "retries": 12,
        "retry_sleep_functions": {
            "extractor": lambda n: 0.2 * n,
            "http": lambda n: 0.1 * (2**n),
            "fragment": lambda n: 0.04 * (2**n),
        },
        "outtmpl": {
            "default": out_dir("%(uploader,uploader_id)s/%(title).200B_%(view_count)3.2D_[%(id).60B].%(ext)s"),
            "chapter": out_dir(
                "%(uploader,uploader_id)s/%(title).200B_%(section_number)03d_%(section_title)s_%(view_count)3.2D_[%(id).60B].%(ext)s",
            ),
        },
    }

    if args.profile != DBType.audio:
        func_opts["subtitlesformat"] = "srt/best"
        func_opts["subtitleslangs"] = args.subtitle_languages
        func_opts["writesubtitles"] = args.subs
        func_opts["writeautomaticsub"] = args.auto_subs
        func_opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

    ydl_opts = tube_opts(
        args,
        func_opts=func_opts,
        playlist_opts=m.get("extractor_config", "{}"),
    )

    match_filters = ["live_status=?not_live"]

    if args.small:
        match_filters.append("duration >? 59 & duration <? 14399")
        ydl_opts[
            "format"
        ] = "bestvideo[height<=576][filesize<2G]+bestaudio/best[height<=576][filesize<2G]/bestvideo[height<=576]+bestaudio/best[height<=576]/best"

    if args.profile == DBType.audio:
        ydl_opts[
            "format"
        ] = "bestaudio[ext=opus]/bestaudio[ext=webm]/bestaudio[ext=ogg]/bestaudio[ext=oga]/bestaudio/best"
        if args.ext is None:
            args.ext = "opus"
        ydl_opts["postprocessors"].append({"key": "FFmpegExtractAudio", "preferredcodec": args.ext})

    match_filter_user_config = ydl_opts.get("match_filter")
    if match_filter_user_config is not None:
        match_filters.append(match_filter_user_config)

    def blocklist_check(info, *pargs, incomplete):
        if getattr(args, "blocklist_rules", False):
            media_entry = db_media.consolidate(deepcopy(info))
            if sql_utils.is_blocked_dict_like_sql(media_entry or {}, args.blocklist_rules):
                raise yt_dlp.utils.RejectedVideoReached("Video matched library blocklist")
        ytdlp_match_filter = yt_dlp.utils.match_filter_func(" & ".join(match_filters).split(" | "))
        return ytdlp_match_filter(info, *pargs, incomplete)

    ydl_opts["match_filter"] = blocklist_check

    download_archive = Path(args.download_archive or "~/.local/share/yt_archive.txt").expanduser().resolve()
    if download_archive.exists() and not consts.PYTEST_RUNNING:
        global yt_archive
        ydl_opts["cookiesfrombrowser"] = ("firefox",)
        if len(yt_archive) == 0:
            with yt_dlp.utils.locked_file(str(download_archive), "r", encoding="utf-8") as archive_file:
                for line in archive_file:
                    yt_archive.add(line.strip())
        if len(yt_archive) > 0:  # check again
            ydl_opts["download_archive"] = yt_archive
        else:
            ydl_opts["download_archive"] = str(download_archive)

    webpath = m["path"]
    local_path = None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(webpath, download=True)
        except (
            yt_dlp.DownloadError,
            ConnectionResetError,
            FileNotFoundError,
            yt_dlp.utils.YoutubeDLError,
            yt_dlp.compat.compat_HTMLParseError,
            IndexError,
            RecursionError,
            TypeError,
        ) as e:
            error = consts.REGEX_ANSI_ESCAPE.sub("", str(e))
            ydl_log["error"].append(error)
            info = None
            log.debug("[%s]: yt-dlp %s", webpath, error)
            # media.download_add(args, webpath, error=error)
            # return
        except Exception as e:
            if args.ignore_errors:
                error = consts.REGEX_ANSI_ESCAPE.sub("", str(e))
                ydl_log["error"].append(error)
                info = None
                log.debug("[%s]: yt-dlp %s", webpath, error)
            else:
                log.warning(webpath)
                raise
        else:
            if len(yt_archive) > 0 and info is not None:
                archive_id = ydl._make_archive_id(info)
                if archive_id is None:
                    log.info("archive_id not found %s", info)
                else:
                    yt_archive.add(archive_id)
                    with yt_dlp.utils.locked_file(str(download_archive), "a", encoding="utf-8") as archive_file:
                        archive_file.write(archive_id + "\n")

        if info is None:
            log.debug("[%s]: yt-dlp returned no info", webpath)
        else:
            local_path = info.get("local_path", None)
            if args.profile == DBType.audio:
                local_path = ydl.prepare_filename({**info, "ext": args.ext})
            else:
                local_path = ydl.prepare_filename(info)

    ydl_errors = ydl_log["error"] + ydl_log["warning"]
    ydl_errors = "\n".join([line for line in ydl_errors if not yt_meaningless_errors.match(line)])
    ydl_full_log = ydl_log["error"] + ydl_log["warning"] + ydl_log["info"]

    # log.debug('\n'.join(ydl_full_log))

    if not ydl_log["error"] and info:
        log.debug("[%s]: No news is good news", webpath)
        db_media.download_add(args, webpath, info, local_path)
    elif any(yt_recoverable_errors.match(line) for line in ydl_full_log):
        log.info("[%s]: Recoverable error matched (will try again later). %s", webpath, ydl_errors)
        db_media.download_add(args, webpath, info, local_path, error=ydl_errors)
    elif any(yt_unrecoverable_errors.match(line) for line in ydl_full_log):
        matched_error = [
            m.string for m in iterables.conform([yt_unrecoverable_errors.match(line) for line in ydl_full_log])
        ]
        log.debug("[%s]: Unrecoverable error matched. %s", webpath, ydl_errors or strings.combine(matched_error))
        db_media.download_add(args, webpath, info, local_path, error=ydl_errors, unrecoverable_error=True)
    elif any(prefix_unrecoverable_errors.match(line) for line in ydl_full_log):
        log.warning("[%s]: Prefix error. %s", webpath, ydl_errors)
        raise SystemExit(28)
    else:
        if ydl_errors != "":
            log.error("[%s]: Unknown error. %s", webpath, ydl_errors)
        db_media.download_add(args, webpath, info, local_path, error=ydl_errors)
