import argparse, concurrent.futures, json, math, os, sqlite3, subprocess
from contextlib import suppress
from pathlib import Path
from shutil import which

from library import usage
from library.database.manage import db_history
from library.shrink import process_ffmpeg, process_image, process_text
from library.archive.unardel import replace_media_paths
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    devices,
    file_utils,
    filter_engine,
    iterables,
    nums,
    path_utils,
    printing,
    processes,
    shell_utils,
    sqlgroups,
    strings,
)
from library.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_media)
    arggroups.sql_fs(parser)
    parser.set_defaults(
        local_media_only=True,
        hide_deleted=True,
        cols=["path", "type", "duration", "size", "video_count", "video_codecs", "audio_codecs"],
    )
    arggroups.history(parser)

    arggroups.files(parser)

    parser.add_argument(
        "--valid",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Attempt to process files with valid metadata",
    )
    parser.add_argument(
        "--invalid",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Attempt to process files with invalid metadata",
    )

    parser.add_argument("--min-savings-video", type=nums.float_from_percent, default="5%")
    parser.add_argument("--min-savings-audio", type=nums.float_from_percent, default="10%")
    parser.add_argument("--min-savings-image", type=nums.float_from_percent, default="15%")

    parser.add_argument(
        "--source-audio-bitrate",
        type=nums.human_to_bits,
        default="256kbps",
        help="Used to estimate duration when files are inside of archives or invalid",
    )
    parser.add_argument(
        "--source-video-bitrate",
        type=nums.human_to_bits,
        default="1500kbps",
        help="Used to estimate duration when files are inside of archives or invalid",
    )

    parser.add_argument("--target-audio-bitrate", type=nums.human_to_bits, default="128kbps")
    parser.add_argument("--target-video-bitrate", type=nums.human_to_bits, default="800kbps")
    parser.add_argument("--target-image-size", type=nums.human_to_bytes, default="30KiB")
    parser.add_argument(
        "--transcoding-video-rate", type=float, default=1.8, help="Ratio of duration eg. 4x realtime speed"
    )
    parser.add_argument(
        "--transcoding-audio-rate", type=float, default=150, help="Ratio of duration eg. 100x realtime speed"
    )
    parser.add_argument("--transcoding-image-time", type=float, default=1.5, metavar="SECONDS")

    parser.add_argument("--continue-from", help="Skip media until specific file path is seen")
    parser.add_argument("--move", help="Directory to move successful files")
    parser.add_argument("--move-broken", help="Directory to move unsuccessful files")

    arggroups.process_ffmpeg(parser)
    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-dest")
    arggroups.ocrmypdf(parser)
    arggroups.debug(parser)

    arggroups.database_optional(parser)
    arggroups.paths_or_stdin(parser, required=False)
    args = parser.parse_intermixed_args()
    arggroups.database_paths_post(args, legacy_database=True)
    arggroups.args_post(args, parser)

    arggroups.files_post(args)
    arggroups.sql_fs_post(args)
    arggroups.process_ffmpeg_post(args)
    arggroups.ocrmypdf_post(args)

    return args


def collect_media(args) -> list[dict]:
    FFMPEG_INSTALLED = which("ffmpeg")
    IM7_INSTALLED = which("magick")
    CALIBRE_INSTALLED = which("ebook-convert")
    UNAR_INSTALLED = which("lsar")

    if not FFMPEG_INSTALLED:
        log.warning("ffmpeg not installed. Video and Audio files will be skipped")
    if not IM7_INSTALLED:
        log.warning("ImageMagick not installed. Image files will be skipped")
    if not CALIBRE_INSTALLED:
        log.warning("Calibre not installed. Text files will be skipped")
    if not UNAR_INSTALLED:
        log.warning("unar not installed. Archives will not be extracted")

    default_exts = (
        (consts.AUDIO_ONLY_EXTENSIONS - set(("opus", "mka")) if FFMPEG_INSTALLED else set())
        | (consts.VIDEO_EXTENSIONS if FFMPEG_INSTALLED else set())
        | (consts.IMAGE_EXTENSIONS - set(("avif",)) if IM7_INSTALLED else set())
        | (consts.CALIBRE_EXTENSIONS if CALIBRE_INSTALLED else set())
        | (consts.ARCHIVE_EXTENSIONS if UNAR_INSTALLED else set())
    )

    if args.database:
        media = collect_database_media(args, default_exts)
    else:
        media = shell_utils.gen_d(args, default_exts)

        media = filter_engine.filter_items_by_criteria(args, media)
        media = [d if "size" in d else file_utils.get_file_stats(d) for d in media]
    return media


def collect_database_media(args, default_exts) -> list[dict]:
    db_history.create(args)

    if not args.ext:
        or_conditions = [f"m.path like '%.{ext}'" for ext in default_exts]
        args.filter_sql.append(f" AND ({' OR '.join(or_conditions)})")

    fetch_all_for_processed = args.processed is not None
    requested_limit = args.limit
    requested_offset = args.offset
    media = filter_engine.query_db_for_filters(
        args,
        lambda query_args: (
            sqlgroups.media_sql(query_args)
            if query_args.database
            else sqlgroups.fs_sql(query_args, query_args.limit)
        ),
        fetch_all=fetch_all_for_processed,
    )
    try:
        media = list(args.db.query(*media))
    except sqlite3.OperationalError:
        media = list(
            args.db.query(
                *filter_engine.query_db_for_filters(
                    args,
                    lambda query_args: sqlgroups.fs_sql(query_args, query_args.limit),
                    fetch_all=fetch_all_for_processed,
                )
            )
        )
    media = filter_engine.filter_processed(args, media)
    if fetch_all_for_processed:
        if requested_offset:
            media = media[requested_offset:]
        if requested_limit:
            media = media[:requested_limit]
    return media


def check_shrink(args, m) -> list:
    m["ext"] = path_utils.ext(m["path"])
    filetype = (m.get("type") or "").lower()

    if not m["size"]:  # empty or deleted file
        return []

    if (
        (filetype and (filetype.startswith("audio/") or " audio" in filetype))
        or m["ext"] in consts.AUDIO_ONLY_EXTENSIONS
    ) and (m.get("video_count") or 0) == 0:
        is_invalid = False
        m["media_type"] = "Audio"

        if m.get("compressed_size"):
            m["duration"] = m["size"] / args.source_audio_bitrate * 8

        if "duration" not in m:
            try:
                probe = processes.FFProbe(m["path"])
                m["duration"] = probe.duration
            except (TimeoutError, subprocess.TimeoutExpired):
                log.error(f"FFProbe timed out. {m['path']}")
                m["duration"] = None
            except processes.UnplayableFileError:
                m["duration"] = None
                if args.delete_unplayable:
                    log.warning("Deleting unplayable (ffprobe): %s", m["path"])
                    if not args.simulate:
                        Path(m["path"]).unlink(missing_ok=True)
                    return []
        if m["duration"] is None or not m["duration"] > 0:
            log.debug("[%s]: Invalid duration", m["path"])
            m["duration"] = m["size"] / args.source_audio_bitrate * 8
            is_invalid = True

        if (m.get("audio_codecs") or "") == "opus":
            log.debug("[%s]: Already opus", m["path"])
            return []

        future_size = int(m["duration"] * (args.target_audio_bitrate / 8))
        should_shrink_buffer = int(future_size * args.min_savings_audio)

        m["future_size"] = future_size
        m["savings"] = (m.get("compressed_size") or m["size"]) - future_size
        m["processing_time"] = math.ceil(m["duration"] / args.transcoding_audio_rate)

        can_shrink = m["size"] > (future_size + should_shrink_buffer)

        if is_invalid and args.invalid:
            return [m]
        elif args.valid and can_shrink:
            return [m]
        else:
            log.debug("[%s]: skipping; future file size estimated to be larger than source file", m["path"])
    elif (
        (filetype and (filetype.startswith("image/") or " image" in filetype))
        or m["ext"] in consts.IMAGE_EXTENSIONS - consts.IMAGE_ANIMATION_EXTENSIONS
    ) and (m.get("duration") or 0) == 0:
        if m["ext"] == "avif":
            log.debug("Skipping existing AVIF")
            return []

        future_size = args.target_image_size
        should_shrink_buffer = int(future_size * args.min_savings_image)
        can_shrink = m["size"] > (future_size + should_shrink_buffer)

        m["media_type"] = "Image"
        m["future_size"] = future_size
        m["savings"] = (m.get("compressed_size") or m["size"]) - future_size
        m["processing_time"] = args.transcoding_image_time

        if can_shrink:
            return [m]
        log.debug("[%s]: skipping; future file size estimated to be larger than source file", m["path"])
    elif (
        (filetype and (filetype.startswith("video/") or " video" in filetype))
        or m["ext"] in consts.VIDEO_EXTENSIONS | consts.IMAGE_ANIMATION_EXTENSIONS
    ) and (m.get("video_count") or 1) >= 1:
        is_invalid = False
        m["media_type"] = "Video"

        if m.get("compressed_size"):
            m["duration"] = m["size"] / args.source_video_bitrate * 8

        if "duration" not in m:
            try:
                probe = processes.FFProbe(m["path"])
                m["duration"] = probe.duration
            except (TimeoutError, subprocess.TimeoutExpired):
                log.error(f"FFProbe timed out. {m['path']}")
                m["duration"] = None
            except processes.UnplayableFileError:
                m["duration"] = None
                if args.delete_unplayable:
                    log.warning("Deleting unplayable (ffprobe): %s", m["path"])
                    if not args.simulate:
                        Path(m["path"]).unlink(missing_ok=True)
                    return []
        if m["duration"] is None or not m["duration"] > 0 or m["ext"] in consts.SKIP_MEDIA_CHECK:
            log.debug("[%s]: Invalid duration", m["path"])
            m["duration"] = m["size"] / args.source_video_bitrate * 8
            is_invalid = True

        if (m.get("video_codecs") or "") == "av1":
            log.debug("[%s]: Already AV1", m["path"])
            return []

        future_size = int(m["duration"] * (args.target_video_bitrate / 8))
        should_shrink_buffer = int(future_size * args.min_savings_video)

        m["future_size"] = future_size
        m["savings"] = (m.get("compressed_size") or m["size"]) - future_size
        m["processing_time"] = math.ceil(m["duration"] / args.transcoding_video_rate)

        can_shrink = m["size"] > (future_size + should_shrink_buffer)

        if is_invalid and args.invalid:
            return [m]
        elif args.valid and can_shrink:
            return [m]
        else:
            log.debug("[%s]: skipping; future file size estimated to be larger than source file", m["path"])
    elif m["ext"] in consts.CALIBRE_EXTENSIONS:
        future_size = args.target_image_size * 50
        should_shrink_buffer = int(future_size * args.min_savings_image)
        can_shrink = m["size"] > (future_size + should_shrink_buffer)

        m["media_type"] = "Text"
        m["future_size"] = future_size
        m["savings"] = (m.get("compressed_size") or m["size"]) - future_size
        m["processing_time"] = args.transcoding_image_time * 12
        if can_shrink:
            return [m]
        else:
            log.debug("[%s]: skipping; future file size estimated to be larger than source file", m["path"])
    elif m.get("compressed_size"):
        log.info("[%s]: Skipping unknown filetype %s from archive", m["path"], m["ext"])
        # m["media_type"] = "Compressed"
        # return [m]
    elif (filetype and (filetype.startswith("archive/") or filetype.endswith("+zip") or " archive" in filetype)) or m[
        "ext"
    ] in consts.ARCHIVE_EXTENSIONS:
        contents = processes.lsar(m["path"])
        if contents:
            return [check_shrink(args, d) for d in contents]
        elif args.move_broken:
            part_files = [m["path"]]
            with suppress(subprocess.CalledProcessError, json.JSONDecodeError):
                lsar_output = processes.cmd("lsar", "-json", m["path"], error_verbosity=2, nice=7)
                lsar_json = strings.safe_json_loads(lsar_output.stdout)
                part_files = lsar_json["lsarProperties"]["XADVolumes"]

            for p in part_files:
                dest = path_utils.relative_from_mountpoint(p, args.move_broken)
                shell_utils.rename_move_file(p, dest, simulate=args.simulate)
    else:
        log.warning("[%s]: Skipping unknown filetype %s %s", m["path"], m["ext"], filetype)
    # TODO?: csv, json => parquet
    return []


def _archive_paths(media):
    return list(
        dict.fromkeys(
            str(m["path"])
            for m in media
            if m.get("path") and processes.is_archive_path(m["path"])
        )
    )


def _archive_contains_nested_archive(archive_path):
    return any(
        processes.is_archive_path(item.get("rel_path") or item.get("path", ""))
        for item in processes.lsar(archive_path)
    )


def extract_nested_media(args, media, archive_paths, mp_args):
    """Extract selected archives and add processable files from nested archives."""
    extracted_outputs = []
    path_updates = []

    for archive_path in archive_paths:
        if not os.path.exists(archive_path):
            continue
        if args.simulate:
            log.info("Unarchiving %s", archive_path)
            continue

        output_path, updates = processes.extract_nested_archives(
            archive_path,
            flatten=False,
        )
        extracted_outputs.append(output_path)
        path_updates.extend(updates)

    original_media_paths = {m["path"] for m in media}
    media = replace_media_paths(media, path_updates)
    if args.simulate:
        return media

    existing_paths = {m["path"] for m in media} | original_media_paths
    for output_path in extracted_outputs:
        for path in processes.iter_regular_files(output_path):
            if path in existing_paths or processes.is_archive_path(path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue

            nested_media = check_shrink(mp_args, {"path": path, "size": size})
            for item in iterables.conform(nested_media):
                if item["path"] not in existing_paths:
                    media.append(item)
                    existing_paths.add(item["path"])

    return iterables.list_dict_unique(media, ["path"])


def process_media() -> None:
    args = parse_args()
    collected_media = collect_media(args)
    collected_archive_paths = _archive_paths(collected_media)

    mp_args = argparse.Namespace(**{k: v for k, v in args.__dict__.items() if k != "db"})
    with concurrent.futures.ThreadPoolExecutor() as executor:  # mostly for lsar but also ffprobe
        futures = {executor.submit(check_shrink, mp_args, m) for m in collected_media}
    media = iterables.conform(v.result() for v in futures)

    media = sorted(
        media, key=lambda d: d["savings"] / (d["processing_time"] or args.transcoding_image_time), reverse=True
    )

    if args.continue_from:
        media = iterables.tail_from(media, args.continue_from, key="path")

    media = iterables.list_dict_unique(media, ["path"])

    if media:
        archive_paths = list(
            dict.fromkeys(
                str(m["archive_path"])
                for m in media
                if m.get("archive_path") and m.get("compressed_size")
            )
        )
    else:
        archive_paths = [
            archive_path
            for archive_path in collected_archive_paths
            if _archive_contains_nested_archive(archive_path)
        ]

    if not media and not archive_paths:
        processes.no_media_found()

    summary = {}
    for m in media:
        media_key = f"{m['media_type']}: {m['ext']}"
        if m.get("compressed_size"):
            media_key += " (archived)"

        if media_key not in summary:
            summary[media_key] = {
                "count": 0,
                "compressed_size": 0,
                "current_size": 0,
                "future_size": 0,
                "savings": 0,
                "processing_time": 0,
            }
        summary[media_key]["count"] += 1
        summary[media_key]["current_size"] += m["size"]
        summary[media_key]["future_size"] += m["future_size"]
        summary[media_key]["savings"] += m["savings"]
        summary[media_key]["compressed_size"] += m.get("compressed_size") or 0
        summary[media_key]["processing_time"] += m.get("processing_time") or 0

    summary = [{"media_key": k, **v} for k, v in summary.items()]
    current_size = sum([m["current_size"] for m in summary])
    future_size = sum([m["future_size"] for m in summary])
    savings = sum([m["savings"] for m in summary])
    processing_time = sum([m["processing_time"] for m in summary])

    summary = sorted(summary, key=lambda d: d["savings"], reverse=True)
    summary = iterables.list_dict_filter_bool(summary, keep_0=False)

    if summary:
        for t in ["processing_time"]:
            summary = printing.col_duration(summary, t)
        for t in ["current_size", "future_size", "compressed_size", "savings"]:
            summary = printing.col_filesize(summary, t)
        printing.table(summary)
        print()

    print("Current size:", strings.file_size(current_size))
    print("Estimated future size:", strings.file_size(future_size))
    print("Estimated savings:", strings.file_size(savings))
    print("Estimated processing time:", strings.duration(processing_time))

    new_free_space = 0
    if args.no_confirm or devices.confirm("Proceed?"):
        media = extract_nested_media(args, media, archive_paths, mp_args)
        media = sorted(
            media, key=lambda d: d["savings"] / (d["processing_time"] or args.transcoding_image_time), reverse=True
        )
        if args.continue_from:
            media = iterables.tail_from(media, args.continue_from, key="path")
        for m in media:
            log.info(
                "%s freed. Processing %s (%s)",
                strings.file_size(new_free_space),
                m["path"],
                strings.file_size(m["size"]),
            )

            if not os.path.exists(m["path"]):
                log.error("[%s]: FileNotFoundError", m["path"])
                m["time_deleted"] = consts.APPLICATION_START
                if args.database and not args.simulate:
                    with suppress(sqlite3.OperationalError), args.db.conn:
                        args.db.conn.execute(
                            "UPDATE media set time_deleted = ? where path = ?", [m["time_deleted"], m["path"]]
                        )
                continue

            if args.simulate:
                if m["media_type"] in ("Audio", "Video"):
                    log.info("FFMPEG processing %s", m["path"])
                elif m["media_type"] == "Image":
                    log.info("ImageMagick processing %s", m["path"])
                elif m["media_type"] == "Text":
                    log.info("Calibre processing %s", m["path"])
                else:
                    raise NotImplementedError

                new_free_space += (m.get("compressed_size") or m["size"]) - m["future_size"]
            else:
                try:
                    if m["media_type"] in ("Audio", "Video"):
                        new_path = process_ffmpeg.process_path(args, m["path"])
                    elif m["media_type"] == "Image":
                        new_path = process_image.process_path(args, m["path"])
                    elif m["media_type"] == "Text":
                        new_path = process_text.process_path(args, m["path"])
                    else:
                        raise NotImplementedError
                except (subprocess.CalledProcessError, processes.UnplayableFileError):
                    new_path = None

                if new_path is None:
                    m["time_deleted"] = consts.APPLICATION_START
                elif isinstance(new_path, list):
                    new_outputs = []
                    for output_path in new_path:
                        output_path = str(output_path)
                        try:
                            duration = processes.FFProbe(output_path).duration
                        except (TimeoutError, subprocess.TimeoutExpired):
                            log.error(f"FFProbe timed out. {output_path}")
                            continue
                        except processes.UnplayableFileError:
                            if args.delete_unplayable:
                                log.warning("Deleting unplayable (ffprobe): %s", output_path)
                                Path(output_path).unlink(missing_ok=True)
                            continue
                        new_outputs.append(
                            {
                                "path": output_path,
                                "size": os.stat(output_path).st_size,
                                "duration": duration,
                            }
                        )

                    if len(new_outputs) != len(new_path):
                        m["time_deleted"] = consts.APPLICATION_START
                    else:
                        m["new_outputs"] = new_outputs
                        m["new_path"] = new_outputs[0]["path"]
                        m["new_size"] = new_outputs[0]["size"]
                        m["total_new_size"] = sum(output["size"] for output in new_outputs)
                        m["duration"] = new_outputs[0]["duration"]
                elif new_path == m["path"]:
                    if args.move:
                        # move original file
                        dest = path_utils.relative_from_mountpoint(m["path"], args.move)
                        shell_utils.rename_move_file(m["path"], dest)
                    continue
                else:
                    if m["media_type"] in ("Audio", "Video", "Image"):
                        m["new_path"] = str(new_path)
                        m["new_size"] = os.stat(new_path).st_size
                    elif m["media_type"] == "Text":
                        m["new_path"] = str(new_path)
                        for p in [
                            os.path.join(new_path, "index.html"),
                            os.path.join(new_path, "OEBPS"),
                        ]:
                            if os.path.exists(p):
                                m["new_path"] = p
                                break

                        m["new_size"] = path_utils.folder_size(new_path)

                    if m["media_type"] in ("Audio", "Video"):
                        try:
                            m["duration"] = processes.FFProbe(new_path).duration
                        except (TimeoutError, subprocess.TimeoutExpired):
                            log.error(f"FFProbe timed out. {new_path}")
                            continue
                        except processes.UnplayableFileError:
                            if args.delete_unplayable:
                                log.warning("Deleting unplayable (ffprobe): %s", new_path)
                                Path(new_path).unlink(missing_ok=True)
                            continue

                    if not os.path.exists(m["path"]):
                        new_free_space += (m.get("compressed_size") or m["size"]) - m.get(
                            "total_new_size", m["new_size"]
                        )

                if args.move and not m.get("time_deleted") and m.get("new_path"):
                    if m.get("new_outputs"):
                        for output in m["new_outputs"]:
                            dest = path_utils.relative_from_mountpoint(output["path"], args.move)
                            shell_utils.rename_move_file(output["path"], dest)
                            output["path"] = dest
                        m["new_path"] = m["new_outputs"][0]["path"]
                    else:
                        dest = path_utils.relative_from_mountpoint(m["new_path"], args.move)
                        shell_utils.rename_move_file(m["new_path"], dest)
                elif args.move_broken and m.get("time_deleted") and os.path.exists(m["path"]):
                    dest = path_utils.relative_from_mountpoint(m["path"], args.move_broken)
                    shell_utils.rename_move_file(m["path"], dest)

                if args.database:
                    with suppress(sqlite3.OperationalError), args.db.conn:
                        if m.get("time_deleted"):
                            args.db.conn.execute(
                                "UPDATE media set time_deleted = ? where path = ?", [m["time_deleted"], m["path"]]
                            )
                        elif m.get("new_path") and m.get("new_path") != m["path"]:
                            args.db.conn.execute("DELETE FROM media where path = ?", [m["new_path"]])
                            args.db.conn.execute(
                                "UPDATE media SET path = ?, size = ?, duration = ? WHERE path = ?",
                                [m["new_path"], m["new_size"], nums.safe_int(m.get("duration")), m["path"]],
                            )
                            if m.get("new_outputs"):
                                media_columns = db_utils.columns(args, "media")
                                for output in m["new_outputs"][1:]:
                                    args.db.conn.execute("DELETE FROM media where path = ?", [output["path"]])
                                    entry = {
                                        key: value
                                        for key, value in m.items()
                                        if key in media_columns and key not in {"id", "path", "size", "duration"}
                                    }
                                    entry |= output
                                    args.db["media"].insert(
                                        entry,
                                        pk=["playlists_id", "path"],
                                        alter=False,
                                        replace=True,
                                    )
