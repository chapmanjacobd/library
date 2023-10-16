import fractions, json, math, subprocess
from datetime import datetime
from typing import Dict, Optional

import ffmpeg

from xklb.media import subtitle
from xklb.utils import consts, file_utils, iterables, nums, objects, printing, processes, strings
from xklb.utils.consts import DBType
from xklb.utils.log_utils import log


def get_subtitle_tags(args, path, streams, codec_types) -> dict:
    attachment_count = sum(1 for s in codec_types if s == "attachment")
    internal_subtitles_count = sum(1 for s in codec_types if s == "subtitle")

    subtitles = []
    if args.scan_subtitles:
        internal_subtitles = subtitle.externalize_internal_subtitles(path, streams)
        external_subtitles = subtitle.get_external(path)

        for subtitle_path in internal_subtitles + external_subtitles:
            try:
                captions = subtitle.read_sub(subtitle_path)
            except UnicodeDecodeError:
                log.warning(f"Could not decode subtitle {subtitle_path} for {path}")
            else:
                subtitles.extend(captions)
    else:
        external_subtitles = []

    video_tags = {
        "subtitle_count": internal_subtitles_count + len(external_subtitles),
        "attachment_count": attachment_count,
        "subtitles": subtitles,
    }

    return video_tags


def parse_tags(mu: Dict, ti: Dict) -> dict:
    tags = {
        "mood": strings.combine(
            mu.get("albummood"),
            mu.get("MusicMatch_Situation"),
            mu.get("Songs-DB_Occasion"),
            mu.get("albumgrouping"),
        ),
        "genre": strings.combine(mu.get("genre"), ti.get("genre"), mu.get("albumgenre")),
        "year": strings.combine(
            mu.get("originalyear"),
            mu.get("TDOR"),
            mu.get("TORY"),
            mu.get("date"),
            mu.get("TDRC"),
            mu.get("TDRL"),
            ti.get("year"),
        ),
        "bpm": nums.safe_int(iterables.safe_unpack(mu.get("fBPM"), mu.get("bpm"), mu.get("bpm_start"))),
        "key": iterables.safe_unpack(mu.get("TIT1"), mu.get("key"), mu.get("TKEY"), mu.get("key_start")),
        "decade": iterables.safe_unpack(mu.get("Songs-DB_Custom1")),
        "categories": iterables.safe_unpack(mu.get("Songs-DB_Custom2")),
        "city": iterables.safe_unpack(mu.get("Songs-DB_Custom3")),
        "country": strings.combine(
            mu.get("Songs-DB_Custom4"),
            mu.get("MusicBrainz Album Release Country"),
            mu.get("musicbrainz album release country"),
            mu.get("language"),
        ),
        "description": strings.combine(
            mu.get("description"),
            mu.get("lyrics"),
            ti.get("comment"),
        ),
        "album": iterables.safe_unpack(ti.get("album"), mu.get("album")),
        "title": iterables.safe_unpack(ti.get("title"), mu.get("title")),
        "artist": strings.combine(
            ti.get("artist"),
            mu.get("artist"),
            mu.get("artists"),
            ti.get("albumartist"),
            ti.get("composer"),
        ),
    }

    # print(mutagen)
    # breakpoint()

    return tags


def get_audio_tags(f) -> dict:
    import mutagen
    from tinytag import TinyTag

    try:
        tiny_tags = objects.dict_filter_bool(TinyTag.get(f).as_dict()) or {}
    except Exception:
        tiny_tags = {}

    try:
        mutagen_tags = objects.dict_filter_bool(mutagen.File(f).tags.as_dict()) or {}  # type: ignore
    except Exception:
        mutagen_tags = {}

    stream_tags = parse_tags(mutagen_tags, tiny_tags)
    return stream_tags


def decode_full_scan(path):
    ffprobe_cmd = [
        "ffprobe",
        "-show_entries",
        "stream=r_frame_rate,nb_read_frames,duration",
        "-select_streams",
        "v",
        "-count_frames",
        "-of",
        "json",
        "-threads",
        "5",
        "-v",
        "0",
        path,
    ]

    ffprobe = subprocess.Popen(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = ffprobe.communicate()
    data = json.loads(output)["streams"][0]

    r_frame_rate = fractions.Fraction(data["r_frame_rate"])
    nb_frames = int(data["nb_read_frames"])
    metadata_duration = float(data["duration"])
    actual_duration = nb_frames * r_frame_rate.denominator / r_frame_rate.numerator

    difference = abs(actual_duration - metadata_duration)
    average_duration = (actual_duration + metadata_duration) / 2
    percent_diff = difference / average_duration

    if difference > 0.1:
        log.warning(
            f"Metadata {printing.seconds_to_hhmmss(metadata_duration).strip()} does not match actual duration {printing.seconds_to_hhmmss(actual_duration).strip()} (diff {difference:.2f}s) {path}",
        )

    return percent_diff


def decode_quick_scan(path, scans, scan_duration=3):
    fail_count = 0
    for scan in scans:
        try:
            output = ffmpeg.input(path, ss=scan).output("/dev/null", t=scan_duration, f="null")
            ffmpeg.run(output, quiet=True)
            # ffmpeg -xerror ?
            # I wonder if something like this would be faster: ffmpeg -ss 01:48:00 -i in.mp4 -map 0:v:0 -filter:v "select=eq(pict_type\,I)" -frames:v 1 out.jpg
        except ffmpeg.Error:
            fail_count += 1

    return fail_count / len(scans)


def cover_scan(media_duration, scan_percentage):
    num_scans = max(2, int(math.log(media_duration) * (scan_percentage / 10)))
    scan_duration_total = max(1, media_duration * (scan_percentage / 100))
    scan_duration = max(1, int(scan_duration_total / num_scans))
    scan_interval = media_duration / num_scans

    scans = sorted(set(int(scan * scan_interval) for scan in range(num_scans)))
    if scans[-1] < media_duration - (scan_duration * 2):
        scans.append(math.floor(media_duration - scan_duration))

    return scans, scan_duration


def munge_av_tags(args, media, path) -> Optional[dict]:
    try:
        probe = processes.FFProbe(path)
    except (KeyboardInterrupt, SystemExit) as sys_exit:
        raise SystemExit(130) from sys_exit
    except Exception as e:
        log.error(f"Failed reading header. {path}")
        log.debug(e)
        if args.delete_unplayable and not file_utils.is_file_open(path):
            file_utils.trash(path)
        return None

    if not probe.format:
        log.error(f"Failed reading format. {path}")
        log.warning(probe)
        return None

    format_ = probe.format
    format_.pop("size", None)
    format_.pop("bit_rate", None)
    format_.pop("format_name", None)
    format_.pop("format_long_name", None)
    format_.pop("nb_programs", None)
    format_.pop("nb_streams", None)
    format_.pop("probe_score", None)
    format_.pop("start_time", None)
    format_.pop("filename", None)

    duration = nums.safe_int(format_.pop("duration", None))
    corruption = None
    if args.check_corrupt and args.check_corrupt > 0.0:
        if args.check_corrupt >= 100.0 and args.profile != DBType.video:
            try:
                output = ffmpeg.input(path).output("/dev/null", f="null")
                ffmpeg.run(output, quiet=True)
            except ffmpeg.Error:
                log.warning(f"Data corruption found. {path}")
                if args.delete_corrupt and not consts.PYTEST_RUNNING:
                    file_utils.trash(path)
        else:
            if args.check_corrupt >= 100.0:
                corruption = decode_full_scan(path)
            else:
                corruption = decode_quick_scan(path, *cover_scan(duration, args.check_corrupt))

            DEFAULT_THRESHOLD = 0.02
            if corruption > DEFAULT_THRESHOLD:
                log.warning(f"Data corruption found ({corruption:.2%}). {path}")
            if args.delete_corrupt and corruption > args.delete_corrupt and not consts.PYTEST_RUNNING:
                file_utils.trash(path)

    tags = format_.pop("tags", None)
    if tags:
        upload_date = tags.get("DATE")
        if upload_date:
            try:
                upload_date = nums.to_timestamp(datetime.strptime(upload_date, "%Y%m%d"))
            except Exception:
                upload_date = None

        tags = objects.dict_filter_bool(
            {
                "title": tags.get("title"),
                "webpath": tags.get("PURL"),
                "description": strings.combine(
                    tags.get("DESCRIPTION"),
                    tags.get("SYNOPSIS"),
                    tags.get("ARTIST"),
                    tags.get("COMMENT"),
                    tags.get("comment"),
                ),
                "time_uploaded": upload_date,
            },
        )

    if format_ != {}:
        log.info("Extra data %s", format_)

    streams = probe.streams

    def parse_framerate(string) -> Optional[int]:
        top, bot = string.split("/")
        bot = int(bot)
        if bot == 0:
            return None
        return int(int(top) / bot)

    fps = iterables.safe_unpack(
        [
            parse_framerate(s.get("avg_frame_rate"))
            for s in streams
            if s.get("avg_frame_rate") is not None and "/0" not in s.get("avg_frame_rate")
        ]
        + [
            parse_framerate(s.get("r_frame_rate"))
            for s in streams
            if s.get("r_frame_rate") is not None and "/0" not in s.get("r_frame_rate")
        ],
    )
    width = iterables.safe_unpack([s.get("width") for s in streams])
    height = iterables.safe_unpack([s.get("height") for s in streams])
    codec_types = [s.get("codec_type") for s in streams]
    stream_tags = [s.get("tags") for s in streams if s.get("tags") is not None]
    language = strings.combine(
        [t.get("language") for t in stream_tags if t.get("language") not in (None, "und", "unk")],
    )

    video_count = sum(1 for s in codec_types if s == "video")
    audio_count = sum(1 for s in codec_types if s == "audio")

    chapters = probe.chapters or []
    chapter_count = len(chapters)
    if chapter_count > 0:
        chapters = [
            {"time": int(float(d["start_time"])), "text": d["tags"]["title"]}
            for d in chapters
            if "tags" in d and "title" in d["tags"] and not strings.is_generic_title(d["tags"]["title"])
        ]

    media = {
        **media,
        "video_count": video_count,
        "audio_count": audio_count,
        "chapter_count": chapter_count,
        "width": width,
        "height": height,
        "fps": fps,
        "duration": 0 if not duration else int(float(duration)),
        "language": language,
        "corruption": nums.safe_int(corruption),
        **(tags or {}),
        "chapters": chapters,
    }

    if args.profile == DBType.video:
        video_tags = get_subtitle_tags(args, path, streams, codec_types)
        media = {**media, **video_tags}
    elif args.profile == DBType.audio:
        stream_tags = get_audio_tags(path)
        media = {**media, **stream_tags}

    return media
