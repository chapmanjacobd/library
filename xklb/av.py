import sys
from typing import Dict, Union

import ffmpeg, mutagen
from tinytag import TinyTag

from xklb import paths, subtitle, utils
from xklb.utils import combine, log, safe_unpack


def get_provenance(file):
    if paths.youtube_dl_id(file) != "":
        return "YouTube"

    return None


def get_subtitle_tags(args, f, streams, codec_types) -> dict:
    attachment_count = sum([1 for s in codec_types if s == "attachment"])
    internal_subtitles_count = sum([1 for s in codec_types if s == "subtitle"])

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


def parse_tags(mutagen: Dict, tinytag: Dict) -> dict:
    tags = {
        "mood": combine(
            mutagen.get("albummood"),
            mutagen.get("MusicMatch_Situation"),
            mutagen.get("Songs-DB_Occasion"),
            mutagen.get("albumgrouping"),
        ),
        "genre": combine(mutagen.get("genre"), tinytag.get("genre"), mutagen.get("albumgenre")),
        "year": combine(
            mutagen.get("originalyear"),
            mutagen.get("TDOR"),
            mutagen.get("TORY"),
            mutagen.get("date"),
            mutagen.get("TDRC"),
            mutagen.get("TDRL"),
            tinytag.get("year"),
        ),
        "bpm": safe_unpack(mutagen.get("fBPM"), mutagen.get("bpm_accuracy")),
        "key": safe_unpack(mutagen.get("TIT1"), mutagen.get("key_accuracy"), mutagen.get("TKEY")),
        "time": combine(mutagen.get("time_signature")),
        "decade": safe_unpack(mutagen.get("Songs-DB_Custom1")),
        "categories": safe_unpack(mutagen.get("Songs-DB_Custom2")),
        "city": safe_unpack(mutagen.get("Songs-DB_Custom3")),
        "country": combine(
            mutagen.get("Songs-DB_Custom4"),
            mutagen.get("MusicBrainz Album Release Country"),
            mutagen.get("musicbrainz album release country"),
            mutagen.get("language"),
        ),
        "description": combine(
            mutagen.get("description"),
            mutagen.get("lyrics"),
            tinytag.get("comment"),
        ),
        "album": safe_unpack(tinytag.get("album"), mutagen.get("album")),
        "title": safe_unpack(tinytag.get("title"), mutagen.get("title")),
        "artist": combine(
            tinytag.get("artist"),
            mutagen.get("artist"),
            mutagen.get("artists"),
            tinytag.get("albumartist"),
            tinytag.get("composer"),
        ),
    }

    # print(mutagen)
    # breakpoint()

    return tags


def get_audio_tags(f) -> dict:
    try:
        tiny_tags = utils.dict_filter_bool(TinyTag.get(f).as_dict())
    except Exception:
        tiny_tags = dict()

    try:
        mutagen_tags = utils.dict_filter_bool(mutagen.File(f).tags.as_dict())  # type: ignore
    except Exception:
        mutagen_tags = dict()

    stream_tags = parse_tags(mutagen_tags, tiny_tags)
    return stream_tags


def munge_av_tags(args, media, f) -> Union[dict, None]:
    try:
        probe = ffmpeg.probe(f, show_chapters=None)
    except (KeyboardInterrupt, SystemExit):
        exit(130)
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

    format = probe["format"]
    format.pop("size", None)
    format.pop("tags", None)
    format.pop("bit_rate", None)
    format.pop("format_name", None)
    format.pop("format_long_name", None)
    format.pop("nb_programs", None)
    format.pop("nb_streams", None)
    format.pop("probe_score", None)
    format.pop("start_time", None)
    format.pop("filename", None)
    duration = format.pop("duration", None)

    if format != {}:
        log.info("Extra data %s", format)
        # breakpoint()

    streams = probe["streams"]

    def parse_framerate(string) -> Union[int, None]:
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
    language = combine([t.get("language") for t in stream_tags if t.get("language") not in [None, "und", "unk"]])

    video_count = sum([1 for s in codec_types if s == "video"])
    audio_count = sum([1 for s in codec_types if s == "audio"])
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
        "provenance": get_provenance(f),
    }

    if args.db_type == "v":
        video_tags = get_subtitle_tags(args, f, streams, codec_types)
        media = {**media, **video_tags}

    if args.db_type == "a":
        stream_tags = get_audio_tags(f)
        media = {**media, **stream_tags}
    return media
