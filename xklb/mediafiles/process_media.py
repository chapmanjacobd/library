import argparse, concurrent.futures, math, os, sqlite3
from contextlib import suppress
from shutil import which

from xklb import usage
from xklb.mediadb import db_history
from xklb.mediafiles import process_ffmpeg, process_image, process_text
from xklb.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    devices,
    file_utils,
    iterables,
    nums,
    path_utils,
    printing,
    processes,
    sqlgroups,
    strings,
)
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_media)
    arggroups.sql_fs(parser)
    parser.set_defaults(
        local_media_only=True,
        hide_deleted=True,
        cols=["path", "type", "duration", "size", "video_count", "video_codecs", "audio_codecs"],
    )
    arggroups.history(parser)

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
        help="Used to estimate duration when files are invalid or inside of archives",
    )
    parser.add_argument(
        "--source-video-bitrate",
        type=nums.human_to_bits,
        default="1400kbps",
        help="Used to estimate duration when files are invalid or inside of archives",
    )

    parser.add_argument("--target-audio-bitrate", type=nums.human_to_bits, default="128kbps")
    parser.add_argument("--target-video-bitrate", type=nums.human_to_bits, default="800kbps")
    parser.add_argument("--target-image-size", type=nums.human_to_bytes, default="30KiB")
    parser.add_argument(
        "--transcoding-video-rate", type=float, default=1.8, help="Ratio of duration eg. 4x realtime speed"
    )
    parser.add_argument(
        "--transcoding-audio-rate", type=float, default=70, help="Ratio of duration eg. 100x realtime speed"
    )
    parser.add_argument("--transcoding-image-time", type=float, default=1.5, metavar="SECONDS")

    parser.add_argument("--no-confirm", "--yes", "-y", action="store_true")

    arggroups.process_ffmpeg(parser)
    arggroups.clobber(parser)
    arggroups.ocrmypdf(parser)
    arggroups.debug(parser)

    arggroups.database_or_paths(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    arggroups.process_ffmpeg_post(args)
    arggroups.ocrmypdf_post(args)

    return args


def collect_media(args) -> list[dict]:
    FFMPEG_INSTALLED = which("ffmpeg") or which("ffmpeg.exe")
    IM7_INSTALLED = which("magick")
    CALIBRE_INSTALLED = which("ebook-convert")
    UNAR_INSTALLED = which("lsar")

    default_exts = (
        (consts.AUDIO_ONLY_EXTENSIONS if FFMPEG_INSTALLED else set())
        | (consts.VIDEO_EXTENSIONS if FFMPEG_INSTALLED else set())
        | (consts.IMAGE_EXTENSIONS - set(("avif",)) if IM7_INSTALLED else set())
        | (consts.CALIBRE_EXTENSIONS if CALIBRE_INSTALLED else set())
        | (consts.ARCHIVE_EXTENSIONS if UNAR_INSTALLED else set())
    )

    if args.database:
        db_history.create(args)

        if not args.ext:
            or_conditions = [f"path like '%.{ext}'" for ext in default_exts]
            args.filter_sql.append(f" AND ({' OR '.join(or_conditions)})")

        try:
            media = list(args.db.query(*sqlgroups.media_sql(args)))
        except sqlite3.OperationalError:
            media = list(args.db.query(*sqlgroups.fs_sql(args, args.limit)))
    else:
        media = arg_utils.gen_d(args, default_exts)
        media = [d if "size" in d else file_utils.get_filesize(d) for d in media]
    return media


def check_shrink(args, m) -> list:
    m["ext"] = path_utils.ext(m["path"])
    filetype = (m.get("type") or "").lower()
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
            except processes.UnplayableFile:
                m["duration"] = None
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
            log.debug("[%s]: Skipping small file", m["path"])
    elif (
        (filetype and (filetype.startswith("image/") or " image" in filetype)) or m["ext"] in consts.IMAGE_EXTENSIONS
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
        log.debug("[%s]: Skipping small file", m["path"])
    elif (
        (filetype and (filetype.startswith("video/") or " video" in filetype)) or m["ext"] in consts.VIDEO_EXTENSIONS
    ) and (m.get("video_count") or 1) >= 1:
        is_invalid = False
        m["media_type"] = "Video"

        if m.get("compressed_size"):
            m["duration"] = m["size"] / args.source_video_bitrate * 8

        if "duration" not in m:
            try:
                probe = processes.FFProbe(m["path"])
                m["duration"] = probe.duration
            except processes.UnplayableFile:
                m["duration"] = None
        if m["duration"] is None or not m["duration"] > 0:
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
            log.debug("[%s]: Skipping small file", m["path"])
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
            log.debug("[%s]: Skipping small file", m["path"])
    elif (filetype and (filetype.startswith("archive/") or filetype.endswith("+zip") or " archive" in filetype)) or m[
        "ext"
    ] in consts.ARCHIVE_EXTENSIONS:
        contents = processes.lsar(m["path"])
        return [check_shrink(args, d) for d in contents]
    else:
        # TODO: csv, json => parquet

        if m.get("compressed_size"):
            log.warning("[%s]: Skipping unknown filetype %s from archive", m["path"], m["ext"])
        else:
            log.warning("[%s]: Skipping unknown filetype %s %s", m["path"], m["ext"], filetype)
    return []


def process_media() -> None:
    args = parse_args()
    media = collect_media(args)

    mp_args = argparse.Namespace(**{k: v for k, v in args.__dict__.items() if k not in {"db"}})
    with concurrent.futures.ThreadPoolExecutor() as executor:  # mostly for lsar but also ffprobe
        futures = {executor.submit(check_shrink, mp_args, m) for m in media}
    media = iterables.conform(v.result() for v in futures)

    media = sorted(
        media, key=lambda d: d["savings"] / (d["processing_time"] or args.transcoding_image_time), reverse=True
    )

    if not media:
        processes.no_media_found()

    summary = {}
    for m in media:
        media_key = f"{m['media_type']}: {m['ext']}"
        if m.get("compressed_size"):
            media_key += f" (archived)"

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
    savings = sum([m["savings"] for m in summary])
    if "processing_time" in summary[0]:
        processing_time = sum([m["processing_time"] for m in summary])

    summary = sorted(summary, key=lambda d: d["savings"], reverse=True)
    summary = iterables.list_dict_filter_bool(summary, keep_0=False)

    for t in ["processing_time"]:
        summary = printing.col_duration(summary, t)
    for t in ["current_size", "future_size", "compressed_size", "savings"]:
        summary = printing.col_filesize(summary, t)
    printing.table(summary)
    print()

    print("Estimated processing time:", strings.duration(processing_time))
    print("Estimated savings:", strings.file_size(savings))

    uncompressed_archives = set()
    new_free_space = 0
    if args.no_confirm or devices.confirm(f"Proceed?"):
        for m in media:
            log.info(
                "%s freed. Processing %s (%s)",
                strings.file_size(new_free_space),
                m["path"],
                strings.file_size(m["size"]),
            )

            if m.get("compressed_size"):
                if os.path.exists(m["archive_path"]):
                    if m["archive_path"] in uncompressed_archives:
                        continue
                    uncompressed_archives.add(m["archive_path"])

                    if args.simulate:
                        log.info("Unarchiving %s", m["archive_path"])
                    else:
                        processes.unar_delete(m["archive_path"])

                if not os.path.exists(m["path"]):
                    log.error("[%s]: FileNotFoundError from archive %s", m["path"], m["archive_path"])
                    continue
            else:
                if not os.path.exists(m["path"]):
                    log.error("[%s]: FileNotFoundError", m["path"])
                    m["time_deleted"] = consts.APPLICATION_START
                    if args.database:
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
                if m["media_type"] in ("Audio", "Video"):
                    new_path = process_ffmpeg.process_path(args, m["path"])
                elif m["media_type"] == "Image":
                    new_path = process_image.process_path(args, m["path"])
                elif m["media_type"] == "Text":
                    new_path = process_text.process_path(args, m["path"])
                else:
                    raise NotImplementedError

                if new_path is None:
                    m["time_deleted"] = consts.APPLICATION_START
                elif new_path == m["path"]:
                    continue
                else:
                    if m["media_type"] in ("Audio", "Video", "Image"):
                        m["new_path"] = str(new_path)
                        m["new_size"] = os.stat(new_path).st_size
                    elif m["media_type"] in ("Text",):
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
                        with suppress(processes.UnplayableFile):
                            m["duration"] = processes.FFProbe(new_path).duration

                    new_free_space += (m.get("compressed_size") or m["size"]) - m["new_size"]

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
                                [m["new_path"], m["new_size"], m.get("duration"), m["path"]],
                            )
