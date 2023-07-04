from datetime import datetime, timezone
from typing import Dict, Optional

import ffmpeg

from xklb import consts, subtitle, utils
from xklb.consts import DBType
from xklb.utils import combine, log, safe_unpack


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
                log.warning(f"[{path}] Could not decode subtitle {subtitle_path}")
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
        "mood": combine(
            mu.get("albummood"),
            mu.get("MusicMatch_Situation"),
            mu.get("Songs-DB_Occasion"),
            mu.get("albumgrouping"),
        ),
        "genre": combine(mu.get("genre"), ti.get("genre"), mu.get("albumgenre")),
        "year": combine(
            mu.get("originalyear"),
            mu.get("TDOR"),
            mu.get("TORY"),
            mu.get("date"),
            mu.get("TDRC"),
            mu.get("TDRL"),
            ti.get("year"),
        ),
        "bpm": utils.safe_int(safe_unpack(mu.get("fBPM"), mu.get("bpm"), mu.get("bpm_start"))),
        "key": safe_unpack(mu.get("TIT1"), mu.get("key"), mu.get("TKEY"), mu.get("key_start")),
        "decade": safe_unpack(mu.get("Songs-DB_Custom1")),
        "categories": safe_unpack(mu.get("Songs-DB_Custom2")),
        "city": safe_unpack(mu.get("Songs-DB_Custom3")),
        "country": combine(
            mu.get("Songs-DB_Custom4"),
            mu.get("MusicBrainz Album Release Country"),
            mu.get("musicbrainz album release country"),
            mu.get("language"),
        ),
        "description": combine(
            mu.get("description"),
            mu.get("lyrics"),
            ti.get("comment"),
        ),
        "album": safe_unpack(ti.get("album"), mu.get("album")),
        "title": safe_unpack(ti.get("title"), mu.get("title")),
        "artist": combine(
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
        tiny_tags = utils.dict_filter_bool(TinyTag.get(f).as_dict()) or {}
    except Exception:
        tiny_tags = {}

    try:
        mutagen_tags = utils.dict_filter_bool(mutagen.File(f).tags.as_dict()) or {}  # type: ignore
    except Exception:
        mutagen_tags = {}

    stream_tags = parse_tags(mutagen_tags, tiny_tags)
    return stream_tags


def decode_full_scan(path):
    output = ffmpeg.input(path).output("/dev/null", f="null")
    ffmpeg.run(output, quiet=True)


def decode_quick_scan(path, scans, scan_duration=3):
    fail_count = 0
    for scan in scans:
        try:
            output = ffmpeg.input(path, ss=scan).output("/dev/null", t=scan_duration, f="null")
            ffmpeg.run(output, quiet=True)
        except ffmpeg.Error:
            fail_count += 1

    return (fail_count / len(scans)) * 100


def munge_av_tags(args, media, path) -> Optional[dict]:
    try:
        probe = ffmpeg.probe(path, show_chapters=None)
    except (KeyboardInterrupt, SystemExit) as sys_exit:
        raise SystemExit(130) from sys_exit
    except Exception as e:
        log.error(f"[{path}] Failed reading header. Metadata corruption")
        log.debug(e)
        if args.delete_unplayable:
            utils.trash(path)
        return None

    if "format" not in probe:
        log.error(f"[{path}] Failed reading format")
        log.warning(probe)
        return None

    format_ = probe["format"]
    format_.pop("size", None)
    format_.pop("bit_rate", None)
    format_.pop("format_name", None)
    format_.pop("format_long_name", None)
    format_.pop("nb_programs", None)
    format_.pop("nb_streams", None)
    format_.pop("probe_score", None)
    format_.pop("start_time", None)
    format_.pop("filename", None)

    duration = utils.safe_int(format_.pop("duration", None))

    corruption = None
    if args.check_corrupt and args.check_corrupt > 0.0:
        if args.check_corrupt >= 100.0:
            corruption = 0
            try:
                decode_full_scan(path)
            except ffmpeg.Error:
                corruption = 101
                log.warning(f"[{path}] Data corruption")
                if args.delete_corrupt and not consts.PYTEST_RUNNING:
                    utils.trash(path)
        else:
            corruption = decode_quick_scan(path, *utils.cover_scan(duration, args.check_corrupt))
            if args.delete_corrupt and corruption > args.delete_corrupt:
                log.warning(f"[{path}] Data corruption ({corruption:.2%}) passed threshold ({args.delete_corrupt:.2%})")
                if not consts.PYTEST_RUNNING:
                    utils.trash(path)

    tags = format_.pop("tags", None)
    if tags:
        upload_date = tags.get("DATE")
        if upload_date:
            try:
                upload_date = int(datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                upload_date = None

        tags = utils.dict_filter_bool(
            {
                "title": tags.get("title"),
                "webpath": tags.get("PURL"),
                "description": combine(
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

    streams = probe["streams"]

    def parse_framerate(string) -> Optional[int]:
        top, bot = string.split("/")
        bot = int(bot)
        if bot == 0:
            return None
        return int(int(top) / bot)

    fps = safe_unpack(
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
    width = safe_unpack([s.get("width") for s in streams])
    height = safe_unpack([s.get("height") for s in streams])
    codec_types = [s.get("codec_type") for s in streams]
    stream_tags = [s.get("tags") for s in streams if s.get("tags") is not None]
    language = combine([t.get("language") for t in stream_tags if t.get("language") not in (None, "und", "unk")])

    video_count = sum(1 for s in codec_types if s == "video")
    audio_count = sum(1 for s in codec_types if s == "audio")

    chapters = getattr(probe, "chapters", [])
    chapter_count = len(chapters)
    if chapter_count > 0:
        chapters = [
            {"time": int(float(d["start_time"])), "text": d["tags"]["title"]}
            for d in chapters
            if "tags" in d and "title" in d["tags"] and not utils.is_generic_title(d["tags"]["title"])
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
        "corruption": utils.safe_int(corruption),
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
