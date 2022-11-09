import sys
from datetime import datetime
from typing import Dict, Optional

import ffmpeg, mutagen
from tinytag import TinyTag

from xklb import subtitle, utils
from xklb.consts import DBType
from xklb.utils import combine, log, safe_unpack


def get_subtitle_tags(args, f, streams, codec_types) -> dict:
    attachment_count = sum(1 for s in codec_types if s == "attachment")
    internal_subtitles_count = sum(1 for s in codec_types if s == "subtitle")

    if args.scan_subtitles:
        internal_subtitles_text = utils.conform(
            [
                subtitle.extract(f, s["index"])
                for s in streams
                if s.get("codec_type") == "subtitle" and s.get("codec_name") not in subtitle.IMAGE_SUBTITLE_CODECS
            ],
        )

        external_subtitles = subtitle.get_external(f)
        subs_text = subtitle.subs_to_text(f, internal_subtitles_text + external_subtitles)
    else:
        external_subtitles = []
        subs_text = []

    video_tags = {
        "subtitle_count": internal_subtitles_count + len(external_subtitles),
        "attachment_count": attachment_count,
        "tags": combine(subs_text),
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
        "bpm": safe_unpack(mu.get("fBPM"), mu.get("bpm_accuracy")),
        "key": safe_unpack(mu.get("TIT1"), mu.get("key_accuracy"), mu.get("TKEY")),
        "time": combine(mu.get("time_signature")),
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


def munge_av_tags(args, media, f) -> Optional[dict]:
    try:
        probe = ffmpeg.probe(f, show_chapters=None)
    except (KeyboardInterrupt, SystemExit):
        raise SystemExit(130)
    except Exception as e:
        print(f"[{f}] Failed reading header", file=sys.stderr)
        log.debug(e)
        if args.delete_unplayable:
            utils.trash(f)
        return

    if not "format" in probe:
        print(f"[{f}] Failed reading format", file=sys.stderr)
        print(probe)
        return

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

    duration = format_.pop("duration", None)
    tags = format_.pop("tags", None)
    if tags:
        upload_date = tags.get("DATE")
        if upload_date:
            upload_date = int(datetime.strptime(upload_date, "%Y%m%d").timestamp())
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
                "time_created": upload_date,
            }
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
        ]
    )
    width = safe_unpack([s.get("width") for s in streams])
    height = safe_unpack([s.get("height") for s in streams])
    codec_types = [s.get("codec_type") for s in streams]
    stream_tags = [s.get("tags") for s in streams if s.get("tags") is not None]
    language = combine([t.get("language") for t in stream_tags if t.get("language") not in (None, "und", "unk")])

    video_count = sum(1 for s in codec_types if s == "video")
    audio_count = sum(1 for s in codec_types if s == "audio")
    chapter_count = len(probe["chapters"])

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
        **(tags or {}),
    }

    if args.profile == DBType.video:
        video_tags = get_subtitle_tags(args, f, streams, codec_types)
        media = {**media, **video_tags}

    if args.profile == DBType.audio:
        stream_tags = get_audio_tags(f)
        media = {**media, **stream_tags}
    return media
