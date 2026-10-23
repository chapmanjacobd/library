import functools
import json, re, subprocess, sys
from copy import deepcopy
from pathlib import Path
from subprocess import CalledProcessError
from types import ModuleType

from library.database.add import subtitle
from library.data.yt_dlp_errors import (
    environment_errors,
    yt_filtered,
    yt_meaningless_errors,
    yt_recoverable_errors,
    yt_unrecoverable_errors,
)
from library.database.manage import db_media, db_playlists
from library.file import media_check
from library.utils import consts, db_utils, iterables, objects, path_utils, printing, shell_utils, sql_utils, strings
from library.utils.consts import DBType, DLStatus, VideoArchiveError
from library.utils.log_utils import Timer, log
from library.utils.processes import FFProbe

MAX_CORRUPTION_SCORE = 7

yt_archive = set()


@functools.cache
def load_module_level_yt_dlp() -> ModuleType:
    import yt_dlp

    return yt_dlp


ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10}[AEIMQUYcgkosw048]$")
PATTERNS = [
    re.compile(
        r"(?:https?://)?(?:\w+\.)?youtube\.com/watch/?\?v=([A-Za-z0-9_-]{10}[AEIMQUYcgkosw048])(?:[\/&].*)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:https?://)?(?:\w+\.)?youtube.com/(?:v|embed|shorts|video)/([A-Za-z0-9_-]{10}[AEIMQUYcgkosw048])(?:[\/&].*)?",
        re.IGNORECASE,
    ),
    re.compile(r"(?:https?://)?youtu.be/([A-Za-z0-9_-]{10}[AEIMQUYcgkosw048])(?:\?.*)?", re.IGNORECASE),
]


def coerce_to_yt_id(s):
    if not s:
        return None

    if re.match(ID_PATTERN, s):
        return s

    for pattern in PATTERNS:
        vid = re.sub(pattern, lambda match: match.group(1), s)
        if re.match(ID_PATTERN, vid):
            return vid

    return None


def tube_opts(args, func_opts=None, playlist_opts: str | None = None) -> dict:
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
        "no_check_certificate": True,
        "skip_playlist_after_errors": 21,
        "clean_infojson": False,
        "playlistend": consts.DEFAULT_PLAYLIST_LIMIT,
        "compat_opts": ["no-live-chat"],
    }

    all_opts = {
        **default_opts,
        **func_opts,
        "cookies_from_browser": getattr(args, "cookies_from_browser", None),
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

    return all_opts


def is_supported(url) -> bool:  # thank you @dbr
    if consts.REGEX_V_REDD_IT.match(url):
        return True

    if getattr(is_supported, "yt_ies", None) is None:
        yt_dlp = load_module_level_yt_dlp()
        is_supported.yt_ies = yt_dlp.extractor.gen_extractors()

    return _is_supported_cached(url)


@functools.lru_cache(maxsize=8192)
def _is_supported_cached(url) -> bool:
    return any(ie.suitable(url) and ie.IE_NAME != "generic" for ie in is_supported.yt_ies)


class _PlaylistState:
    def __init__(self):
        self.playlists_of_playlists = set()
        self.added_media_count = 0


_playlist_state = _PlaylistState()


def _archive_postprocessor(yt_dlp, args, playlist_path, ydl_opts, playlist_root, retrieved_paths, t, state):
    class ExistingPlaylistVideoReached(yt_dlp.DownloadCancelled):
        pass

    class AddToArchivePP(yt_dlp.postprocessor.PostProcessor):
        def run(self, info) -> tuple[list, dict]:  # pylint: disable=arguments-renamed
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
                        log.debug("playlists.add %s", t.elapsed())

                    if args.ignore_errors:
                        if webpath in state.playlists_of_playlists and not playlist_root:
                            raise ExistingPlaylistVideoReached
                    elif webpath in state.playlists_of_playlists:
                        raise ExistingPlaylistVideoReached

                    get_playlist_metadata(
                        args,
                        webpath,
                        ydl_opts,
                        playlist_root=False,
                        retrieved_paths=retrieved_paths,
                        _state=state,
                    )
                    log.debug("get_playlist_metadata %s", t.elapsed())
                    state.playlists_of_playlists.add(webpath)
                    return [], info

                entry = objects.dumbcopy(info)
                if entry:
                    if db_playlists.media_exists(args, webpath, playlist_path) and not args.ignore_errors:
                        raise ExistingPlaylistVideoReached

                    if not info.get("playlist_id") or webpath == playlist_path:
                        log.warning("Importing playlist-less media %s", playlist_path)
                    else:
                        entry["playlists_id"] = db_playlists.add(args, playlist_path, info, extractor_key=extractor_key)
                        log.debug("playlists.add2 %s", t.elapsed())

                    db_media.playlist_media_add(args, webpath, entry)  # type: ignore
                    log.debug("media.playlist_media_add %s", t.elapsed())

                    state.added_media_count += 1
                    if state.added_media_count > 1:
                        printing.print_overwrite(f"[{playlist_path}] Added {state.added_media_count} media")

            return [], info

    return AddToArchivePP, ExistingPlaylistVideoReached


def _extract_playlist_info(ydl, yt_dlp, args, playlist_path, count_before_extract, error_type, t, state):
    try:
        playlist = ydl.extract_info(playlist_path, download=False, process=True)
        log.debug("ydl.extract_info done %s", t.elapsed())
    except yt_dlp.DownloadError:
        if args.safe:
            log.error("DownloadError skipping %s", playlist_path)
        else:
            log.warning(
                "Could not scrape playlist metadata successfully (will try again [in a few days] during tubeupdate)"
            )
            db_playlists.save_undownloadable(args, playlist_path)
        return False
    except error_type:
        if state.added_media_count > count_before_extract:
            sys.stderr.write("\n")
        db_playlists.log_problem(args, playlist_path)
    else:
        if state.added_media_count > count_before_extract:
            sys.stderr.write("\n")
        if not playlist:
            if args.safe:
                log.error("DownloadError skipping %s", playlist_path)
            else:
                log.warning(
                    "Could not scrape playlist metadata successfully (will try again [in a few days] during tubeupdate)"
                )
                db_playlists.save_undownloadable(args, playlist_path)
    return True


def _update_playlist_frequency(args, playlist_path, count_before_extract, state):
    if args.action != consts.SC.tube_update:
        return
    if state.added_media_count > count_before_extract:
        db_playlists.update_more_frequently(args, playlist_path)
    else:
        db_playlists.update_less_frequently(args, playlist_path)


def get_playlist_metadata(args, playlist_path, ydl_opts, playlist_root=True, retrieved_paths=None, _state=None) -> None:
    if retrieved_paths is None:
        retrieved_paths = set()
    if playlist_path in retrieved_paths:
        return
    retrieved_paths.add(playlist_path)

    state = _playlist_state if _state is None else _state
    yt_dlp = load_module_level_yt_dlp()
    t = Timer()

    AddToArchivePP, ExistingPlaylistVideoReached = _archive_postprocessor(
        yt_dlp, args, playlist_path, ydl_opts, playlist_root, retrieved_paths, t, state
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.add_post_processor(AddToArchivePP(), when="pre_process")

        log.debug("yt-dlp initialized %s", t.elapsed())
        count_before_extract = state.added_media_count
        if _extract_playlist_info(
            ydl, yt_dlp, args, playlist_path, count_before_extract, ExistingPlaylistVideoReached, t, state
        ):
            _update_playlist_frequency(args, playlist_path, count_before_extract, state)


def yt_subs_config(args):
    if args.subs:
        return {"writesubtitles": True, "writeautomaticsub": True}
    elif args.auto_subs:
        return {"writesubtitles": False, "writeautomaticsub": True}
    return {}


def get_extra_metadata(args, playlist_path, playlist_dl_opts=None) -> list[dict] | None:
    yt_dlp = load_module_level_yt_dlp()
    playlist_id = db_playlists.get_id(args, playlist_path, playlist_dl_opts)

    tables = args.db.table_names()
    m_columns = db_utils.columns(args, "media")

    with yt_dlp.YoutubeDL(
        tube_opts(
            args,
            func_opts={
                "subtitlesformat": "srt/best",
                **yt_subs_config(args),
                "subtitleslangs": args.subtitle_languages,
                "extract_flat": False,
                "lazy_playlist": False,
                "check_formats": False,
                "skip_download": True,
                "outtmpl": {
                    "default": str(
                        Path(f"{consts.SUB_TEMP_DIR}/%(id).60B.%(ext)s"),
                    ),
                },
                "ignoreerrors": True,
            },
            playlist_opts=playlist_dl_opts,
        )
    ) as ydl:
        videos = set(
            args.db.execute(
                f"""SELECT
                    id
                    , path
                    , null as playlists_id
                FROM media
                WHERE COALESCE(time_deleted, 0)=0
                    AND path = ?
                    {'and width is null' if 'width' in m_columns else ''}
                """,
                [playlist_path],
            ).fetchall()
        )

        if "playlists" in tables:
            videos |= set(
                args.db.execute(
                    f"""SELECT
                        id
                        , path
                        , playlists_id
                    FROM media
                    WHERE COALESCE(time_deleted, 0)=0
                        AND playlists_id = ?
                        {'AND width is null' if 'width' in m_columns else ''}
                    """,
                        [playlist_id],
                ).fetchall()
            )

        current_video_count = 0
        for media_id, path, playlists_id in videos:
            entry = ydl.extract_info(path)
            if entry is None:
                continue

            chapters = getattr(entry, "chapters", [])
            chapter_count = len(chapters)
            if chapter_count > 0:
                chapters = [
                    {"media_id": media_id, "time": int(float(d["start_time"])), "text": d.get("title")}
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
                        captions.extend([{"media_id": media_id, **d} for d in file_captions])
                if len(captions) > 0:
                    args.db["captions"].insert_all(captions, alter=True)

            entry["playlists_id"] = playlists_id
            entry["chapter_count"] = chapter_count

            db_media.playlist_media_add(args, path, entry)

            current_video_count += 1
            printing.print_overwrite(f"[{playlist_path}] {current_video_count} of {len(videos)} extra metadata fetched")
        print()


def get_video_metadata(args, playlist_path) -> dict | None:
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


def log_error(ydl_log, webpath):
    ydl_full_log = ydl_log["error"] + ydl_log["warning"] + ydl_log["info"]

    ydl_errors = []
    for log_entry in ydl_full_log:
        for line in log_entry.splitlines():
            match = yt_meaningless_errors.match(line)
            if match:
                log.debug("Removed line: '%s' | Match: '%s'", line, match.group(0))
            else:
                ydl_errors.append(line)
    ydl_errors_txt = "\n".join(ydl_errors)

    matched_error = strings.combine([line for line in ydl_errors if environment_errors.match(line)])
    if matched_error:
        log.warning("Environment error %s %s", matched_error, webpath)
        raise SystemExit(28)

    matched_error = strings.combine([line for line in ydl_errors if yt_filtered.match(line)])
    if matched_error:
        log.info("Blocked %s %s", matched_error, webpath)
        return DLStatus.BLOCKED, matched_error

    matched_error = strings.combine([line for line in ydl_errors if yt_recoverable_errors.match(line)])
    if matched_error:
        log.info("Recoverable error matched (will try again later) %s %s", matched_error, webpath)
        return DLStatus.RECOVERABLE_ERROR, matched_error

    matched_error = strings.combine([line for line in ydl_errors if yt_unrecoverable_errors.match(line)])
    if matched_error:
        log.info("Unrecoverable error matched %s %s", matched_error, webpath)
        return DLStatus.UNRECOVERABLE_ERROR, matched_error

    log.error("Unknown error. %s %s", ydl_errors_txt, webpath)
    return DLStatus.UNKNOWN_ERROR, ydl_errors_txt


class _DownloadLogger:
    def __init__(self, ydl_log):
        self.ydl_log = ydl_log

    def debug(self, msg):
        if not msg.startswith("[debug] "):
            self.info(msg)

    def info(self, msg):
        self.ydl_log["info"].append(msg)

    def warning(self, msg):
        self.ydl_log["warning"].append(msg)

    def error(self, msg):
        self.ydl_log["error"].append(msg)


def _download_output_dir(args, path):
    return str(
        Path(
            args.prefix,
            "%(extractor_key,extractor,ie_key).220B",
            "%(uploader,uploader_id,channel,channel_id,creator,artist,author,playlist_uploader,playlist_uploader_id,playlist_channel,playlist_channel_id,webpage_url_basename).220B",
            "%(album,playlist_title,playlist,playlist_id).220B",
            path,
        )
    )


def _yt_cli_to_api(yt_dlp, opts):
    default = yt_dlp.parse_options([]).ydl_opts
    supplied = yt_dlp.parse_options(opts).ydl_opts
    diff = {key: value for key, value in supplied.items() if default[key] != value}
    if diff.get("postprocessors"):
        diff["postprocessors"] = [pp for pp in diff["postprocessors"] if pp not in default["postprocessors"]]
    return diff


def _build_download_options(args, m, yt_dlp, ydl_log):
    ignoreerrors = bool(m.get("time_modified") and m.get("time_modified") > 0)
    func_opts = {
        "ignoreerrors": ignoreerrors,
        "extractor_args": {"youtubetab": {"skip": ["authcheck"]}, "youtube": {"skip": ["hls", "dash"]}},
        "check_formats": "selected",
        "logger": _DownloadLogger(ydl_log),
        "skip_download": False,
        "postprocessors": [{"key": "FFmpegMetadata"}],
        "extract_flat": False,
        "lazy_playlist": True,
        "noplaylist": True,
        "playlist_items": "1",
        "playlist_end": None,
        "extractor_retries": 3,
        "retries": 12,
        "retry_sleep_functions": {
            "extractor": lambda n: 0.2 * n,
            "http": lambda n: 0.08 * (2**n),
            "fragment": lambda n: 0.04 * (2**n),
        },
        "outtmpl": {
            "default": _download_output_dir(args, "%(id).220B.%(ext)s"),
            "chapter": _download_output_dir(args, "%(id).220B.%(section_number)03d.%(ext)s"),
        },
        "outtmpl_na_placeholder": "",
    }
    if args.verbose >= consts.LOG_DEBUG:
        func_opts["progress_hooks"] = [
            lambda d: log.debug(
                f"downloading {d.get('_percent_str')} {d.get('_speed_str')} {d.get('downloaded_bytes')} bytes"
            )
        ]
    if args.profile != DBType.audio:
        func_opts["subtitlesformat"] = "srt/best"
        func_opts["subtitleslangs"] = args.subtitle_languages
        func_opts |= yt_subs_config(args)
        func_opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

    extra_args = _yt_cli_to_api(yt_dlp, getattr(args, "unk", []))
    ydl_opts = tube_opts(
        args,
        func_opts=func_opts | extra_args,
        playlist_opts=m.get("extractor_config", "{}"),
    )
    return ydl_opts, extra_args


def _set_download_filters(args, yt_dlp, ydl_opts):
    match_filters = []
    user_filter = ydl_opts.get("match_filter")
    if user_filter is not None:
        match_filters.append(user_filter)
    if not args.live:
        match_filters.append("live_status=?not_live")
    if args.small:
        if user_filter is None:
            match_filters.append("duration >? 59 & duration <? 14399")
        ydl_opts["format_sort"] = ["res:576", "channels:2"]
        ydl_opts["format"] = (
            "(bestvideo[filesize<2G]+bestaudio/best[filesize<2G]/bestvideo*+bestaudio/best)[format_id!$=-drc][dynamic_range!^=HDR]/bestvideo[filesize<2G]+bestaudio/best[filesize<2G]/bestvideo*+bestaudio/best"
        )
    if args.profile == DBType.audio:
        ydl_opts["format"] = (
            "(bestaudio[ext=opus]/bestaudio[ext=mka]/bestaudio[ext=webm]/bestaudio[ext=ogg]/bestaudio[ext=oga]/bestaudio/best)[format_id!$=-drc]/bestaudio/best"
        )
        ydl_opts["postprocessors"].append({"key": "FFmpegExtractAudio", "preferredcodec": args.extract_audio_ext})

    def blocklist_check(info, *pargs, incomplete):
        if getattr(args, "blocklist_rules", False):
            media_entry = db_media.consolidate(deepcopy(info))
            if sql_utils.is_blocked_dict_like_sql(media_entry or {}, args.blocklist_rules):
                raise yt_dlp.utils.RejectedVideoReached("Video matched library blocklist")
        if match_filters:
            ytdlp_match_filter = yt_dlp.utils.match_filter_func(" & ".join(match_filters).split(" | "))
            return ytdlp_match_filter(info, *pargs, incomplete)
        return None

    ydl_opts["match_filter"] = blocklist_check


def _configure_download_archive(args, yt_dlp, ydl_opts):
    download_archive = Path(args.download_archive or "~/.local/share/yt_archive.txt").expanduser().resolve()
    if download_archive.exists() and not consts.PYTEST_RUNNING:
        if len(yt_archive) == 0:
            with yt_dlp.utils.locked_file(str(download_archive), "r", encoding="utf-8") as archive_file:
                yt_archive.update(line.strip() for line in archive_file)
        if len(yt_archive) > 0:
            ydl_opts["download_archive"] = yt_archive
        else:
            ydl_opts["download_archive"] = str(download_archive)
    return download_archive


def _extract_download_info(args, m, yt_dlp, ydl_opts, extra_args, ydl_log):
    webpath = m["path"]
    local_path = None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        log.debug("[yt-dlp]: Downloading %s", webpath)
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
            ValueError,
        ) as excinfo:
            error = consts.REGEX_ANSI_ESCAPE.sub("", str(excinfo))
            ydl_log["error"].append(error)
            info = None
            log.debug("yt-dlp %s %s", error, webpath)
        except Exception as excinfo:
            if args.ignore_errors:
                error = consts.REGEX_ANSI_ESCAPE.sub("", str(excinfo))
                ydl_log["error"].append(error)
                info = None
                log.debug("yt-dlp %s %s", error, webpath)
            else:
                log.warning(webpath)
                raise

        if info is None:
            log.debug("yt-dlp returned no info %s", webpath)
            return m, local_path, ydl

        info = {**m, **info}
        if args.profile == DBType.audio:
            info = {**info, "ext": args.extract_audio_ext}
        temp_path = ydl.prepare_filename(info)
        if "outtmpl" in extra_args:
            local_path = temp_path
        else:
            local_path = ydl.prepare_filename(
                info,
                outtmpl=_download_output_dir(
                    args,
                    "%(title).170B_%(section_number)03d_%(section_title).80B_%(view_count)3.2D_[%(id).64B].%(ext)s"
                    if "section_number" in info
                    else "%(title).170B_%(view_count)3.2D_[%(id).64B].%(ext)s",
                ),
            )
            local_path = path_utils.clean_path(local_path.encode())
            if Path(temp_path).exists():
                shell_utils.rename_move_file(temp_path, local_path)
            elif Path(local_path).exists():
                local_path = temp_path
    return info, local_path, ydl


def _check_download(args, info, local_path):
    media_check_failed = False
    if info and local_path and Path(local_path).exists():
        log.info("Downloaded to %s %s", local_path, info["path"])
        if getattr(args, "check_corrupt", False) and path_utils.ext(local_path) not in consts.SKIP_MEDIA_CHECK:
            try:
                if args.profile == DBType.audio:
                    dl_probe = FFProbe(local_path)
                    if not dl_probe.has_audio:
                        raise RuntimeError
                corruption = media_check.calculate_corruption(
                    local_path,
                    chunk_size=args.chunk_size,
                    gap=args.gap,
                    full_scan=args.full_scan,
                    full_scan_if_corrupt=args.full_scan_if_corrupt,
                    audio_scan=args.audio_scan,
                    threads=args.same_file_threads,
                )
                info["corruption"] = int(corruption * 100)
            except (RuntimeError, CalledProcessError, TimeoutError, subprocess.TimeoutExpired):
                info["corruption"] = 50
            if info["corruption"] > MAX_CORRUPTION_SCORE:
                media_check_failed = True
    return media_check_failed


def _handle_failed_download(args, m, info, local_path, media_check_failed, ydl_log):
    download_status = DLStatus.SUCCESS
    ydl_errors_txt = ""
    webpath = m["path"]
    if (info and local_path and Path(local_path).exists()) and not media_check_failed:
        return download_status, ydl_errors_txt, media_check_failed

    archives = (
        "https://web.archive.org/web/0id_/http://wayback-fakeurl.archive.org/yt/",
        "https://ghostarchive.org/varchive/",
        "https://preservetube.com/watch?v=",
    )
    if webpath.startswith(archives):
        raise VideoArchiveError
    log.debug(ydl_log)
    download_status, ydl_errors_txt = log_error(ydl_log, webpath)

    if download_status != DLStatus.BLOCKED:
        vid = coerce_to_yt_id(webpath)
        if vid:
            for prefix in archives:
                try:
                    archive_succeeded = download(args, m | {"path": prefix + vid})
                except VideoArchiveError:
                    continue
                if archive_succeeded:
                    download_status = DLStatus.SUCCESS
                    media_check_failed = False
                    break
    return download_status, ydl_errors_txt, media_check_failed


def _save_download_archive(ydl, yt_dlp, _args, m, info, download_archive):
    if len(yt_archive) == 0 or info is None:
        return
    archive_id = ydl._make_archive_id(info)  # noqa: SLF001
    if archive_id is None:
        vid = coerce_to_yt_id(m["path"])
        if vid:
            archive_id = f"youtube {vid}"
        else:
            log.info("archive_id not found %s", info)
    else:
        yt_archive.add(archive_id)
        with yt_dlp.utils.locked_file(str(download_archive), "a", encoding="utf-8") as archive_file:
            archive_file.write(archive_id + "\n")


def download(args, m) -> bool:
    yt_dlp = load_module_level_yt_dlp()
    ydl_log = {"error": [], "warning": [], "info": []}

    ydl_opts, extra_args = _build_download_options(args, m, yt_dlp, ydl_log)
    _set_download_filters(args, yt_dlp, ydl_opts)
    download_archive = _configure_download_archive(args, yt_dlp, ydl_opts)

    info, local_path, ydl = _extract_download_info(args, m, yt_dlp, ydl_opts, extra_args, ydl_log)
    media_check_failed = _check_download(args, info, local_path)
    download_status, ydl_errors_txt, media_check_failed = _handle_failed_download(
        args, m, info, local_path, media_check_failed, ydl_log
    )

    if media_check_failed:
        log.info("Media check failed %s", local_path)
        download_status = DLStatus.RECOVERABLE_ERROR
        ydl_errors_txt = "Media check failed\n" + ydl_errors_txt

    if download_status == DLStatus.SUCCESS and len(yt_archive) > 0 and info is not None:
        _save_download_archive(ydl, yt_dlp, args, m, info, download_archive)

    db_media.download_add(
        args,
        m["path"],
        info,
        local_path,
        error=None if download_status == DLStatus.SUCCESS else ydl_errors_txt,
        mark_deleted=download_status == DLStatus.UNRECOVERABLE_ERROR,
    )
    return download_status in (DLStatus.SUCCESS, DLStatus.UNRECOVERABLE_ERROR)
