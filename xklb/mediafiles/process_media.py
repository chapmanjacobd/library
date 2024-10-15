import argparse, math, os, sqlite3

from xklb import usage
from xklb.mediadb import db_history
from xklb.mediafiles import process_ffmpeg, process_image
from xklb.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    devices,
    file_utils,
    iterables,
    nums,
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

    parser.add_argument("--min-savings-video", type=nums.float_from_percent, default="3%")
    parser.add_argument("--min-savings-audio", type=nums.float_from_percent, default="10%")
    parser.add_argument("--min-savings-image", type=nums.float_from_percent, default="15%")

    parser.add_argument("--target-audio-bitrate", type=nums.human_to_bits, default="144kbps")
    parser.add_argument("--target-video-bitrate", type=nums.human_to_bits, default="800kbps")
    parser.add_argument("--target-image-size", type=nums.human_to_bytes, default="250KiB")
    parser.add_argument(
        "--transcoding-video-rate", type=float, default=1.8, help="Ratio of duration eg. 4x realtime speed"
    )
    parser.add_argument(
        "--transcoding-audio-rate", type=float, default=70, help="Ratio of duration eg. 100x realtime speed"
    )
    parser.add_argument("--transcoding-image-time", type=float, default=2.5, metavar="SECONDS")

    arggroups.process_ffmpeg(parser)
    arggroups.debug(parser)

    arggroups.database_or_paths(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    arggroups.process_ffmpeg_post(args)

    return args


def collect_media(args) -> list[dict]:
    if args.database:
        db_history.create(args)

        try:
            media = list(args.db.query(*sqlgroups.media_sql(args)))
        except sqlite3.OperationalError:
            media = list(args.db.query(*sqlgroups.fs_sql(args, args.limit)))
    else:
        media = arg_utils.gen_d(args)
        media = [d if "size" in d else file_utils.get_filesize(d) for d in media]
    return media


def check_shrink(args, m) -> list:
    m["ext"] = os.path.splitext(m["path"])[1].lower().lstrip(".")
    filetype = (m.get("type") or "").lower()
    if (
        (filetype and (filetype.startswith("audio/") or " audio" in filetype))
        or m["ext"] in consts.AUDIO_ONLY_EXTENSIONS
    ) and (m.get("video_count") or 0) == 0:
        if m.get("compressed_size"):
            m["duration"] = 3 * 60

        if "duration" not in m:
            probe = processes.FFProbe(m["path"])
            m["duration"] = probe.duration
        if m["duration"] is None:
            return []
        if (m.get("audio_codecs") or "") == "opus":
            return []

        future_size = int(m["duration"] * (args.target_audio_bitrate / 8))
        should_shrink_buffer = int(future_size * args.min_savings_audio)
        can_shrink = m["size"] > (future_size + should_shrink_buffer)
        if can_shrink:
            m["media_type"] = "Audio"
            m["future_size"] = future_size
            m["savings"] = (m.get("compressed_size") or m["size"]) - future_size
            m["processing_time"] = math.ceil(m["duration"] / args.transcoding_audio_rate)
            return [m]
        log.debug("Skipping %s", m)
    elif (
        (filetype and (filetype.startswith("image/") or " image" in filetype)) or m["ext"] in consts.IMAGE_EXTENSIONS
    ) and (m.get("duration") or 0) == 0:
        future_size = args.target_image_size
        should_shrink_buffer = int(future_size * args.min_savings_image)
        can_shrink = m["size"] > (future_size + should_shrink_buffer)
        if can_shrink:
            m["media_type"] = "Image"
            m["future_size"] = future_size
            m["savings"] = (m.get("compressed_size") or m["size"]) - future_size
            m["processing_time"] = args.transcoding_image_time
            return [m]
        log.debug("Skipping %s", m)
    elif (
        (filetype and (filetype.startswith("video/") or " video" in filetype)) or m["ext"] in consts.VIDEO_EXTENSIONS
    ) and (m.get("video_count") or 1) >= 1:
        if m.get("compressed_size"):
            m["duration"] = 20 * 60

        if "duration" not in m:
            probe = processes.FFProbe(m["path"])
            m["duration"] = probe.duration
        if m["duration"] is None:
            return []
        if (m.get("video_codecs") or "") == "av1":
            return []

        future_size = int(m["duration"] * (args.target_video_bitrate / 8))
        should_shrink_buffer = int(future_size * args.min_savings_video)
        can_shrink = m["size"] > (future_size + should_shrink_buffer)
        if can_shrink:
            m["media_type"] = "Video"
            m["future_size"] = future_size
            m["savings"] = (m.get("compressed_size") or m["size"]) - future_size
            m["processing_time"] = math.ceil(m["duration"] / args.transcoding_video_rate)
            return [m]
        log.debug("Skipping %s", m)
    elif (filetype and (filetype.startswith("archive/") or filetype.endswith("+zip") or " archive" in filetype)) or m[
        "ext"
    ] in consts.ARCHIVE_EXTENSIONS:
        contents = processes.lsar(m["path"])
        return [check_shrink(args, d) for d in contents]
    else:
        # TODO: pdf => avif
        # TODO: mobi, azw3, pdf => epub
        log.warning("[%s]: Skipping: Unknown filetype %s", m["path"], filetype)
    return []


def process_media() -> None:
    args = parse_args()
    media = collect_media(args)

    media = iterables.conform(check_shrink(args, m) for m in media)
    media = sorted(media, key=lambda d: d["savings"] / d["processing_time"], reverse=True)

    if not media:
        processes.no_media_found()

    summary = {}
    for m in media:
        media_key = f"{m['media_type']}: {m['ext']}"
        if m.get("compressed_size"):
            media_key += f" (archived)"

        if media_key not in summary:
            summary[media_key] = {
                "compressed_size": 0,
                "current_size": 0,
                "future_size": 0,
                "savings": 0,
                "processing_time": 0,
            }
        summary[media_key]["current_size"] += m["size"]
        summary[media_key]["future_size"] += m["future_size"]
        summary[media_key]["savings"] += m["savings"]
        summary[media_key]["compressed_size"] += m.get("compressed_size") or 0
        summary[media_key]["processing_time"] += m.get("processing_time") or 0

    summary = [{"media_key": k, **v} for k, v in summary.items()]
    savings = sum([m["savings"] for m in summary])
    if "processing_time" in summary[0]:
        processing_time = sum([m["processing_time"] for m in summary])

    summary = iterables.list_dict_filter_bool(summary, keep_0=False)
    sum_ext = sorted(summary, key=lambda d: d["savings"], reverse=True)

    for t in ["processing_time"]:
        summary = printing.col_duration(summary, t)
    for t in ["current_size", "future_size", "compressed_size", "savings"]:
        summary = printing.col_filesize(summary, t)
    printing.table(sum_ext)
    print()

    print("Estimated processing time:", strings.duration(processing_time))
    print("Estimated savings:", strings.file_size(savings))

    new_free_space = 0
    if devices.confirm(f"Proceed?"):
        for m in media:
            log.info(
                "%s freed. Processing %s (%s)",
                strings.file_size(new_free_space),
                m["path"],
                strings.file_size(m["size"]),
            )

            if m.get("compressed_size"):
                if os.path.exists(m["archive_path"]):
                    if args.simulate:
                        log.info("Unarchiving %s", m["archive_path"])
                    else:
                        processes.unar_delete(m["archive_path"])
                if not os.path.exists(m["path"]):
                    log.error("%s: FileNotFoundError from archive %s", m["path"], m["archive_path"])
                    continue
            else:
                if not os.path.exists(m["path"]):
                    log.error("%s: FileNotFoundError", m["path"])
                    m["time_deleted"] = consts.APPLICATION_START
                    continue

            new_path = None
            if m["media_type"] in ("Audio", "Video"):
                if args.simulate:
                    log.info("FFMPEG processing %s", m["path"])
                else:
                    new_path = process_ffmpeg.process_path(args, m["path"])
            elif m["media_type"] == "Image":
                if args.simulate:
                    log.info("ImageMagick processing %s", m["path"])
                else:
                    new_path = process_image.process_path(args, m["path"])

            if new_path is not None:
                m["new_path"] = str(new_path)
                m["new_size"] = os.stat(new_path).st_size

                new_free_space += (m.get("compressed_size") or m["size"]) - m["new_size"]

        with args.db.conn:
            for m in media:
                if m.get("time_deleted"):
                    args.db.conn.execute(
                        "UPDATE media set time_deleted = ? where path = ?", [m["time_deleted"], m["path"]]
                    )
                elif m.get("new_path") and m.get("new_path") != m["path"]:
                    args.db.conn.execute("DELETE FROM media where path = ?", [m["new_path"]])
                    args.db.conn.execute("UPDATE media set path = ? where path = ?", [m["new_path"], m["path"]])
                    args.db.conn.execute(
                        "UPDATE media SET path = ?, size = ? WHERE path = ?", [m["new_path"], m["new_size"], m["path"]]
                    )
