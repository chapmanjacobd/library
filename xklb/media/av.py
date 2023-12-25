from datetime import datetime
from typing import Dict, Optional


from xklb.media import subtitle, media_check
from xklb.utils import consts, file_utils, iterables, nums, objects, processes, strings
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


def munge_av_tags(args, media, path) -> Optional[dict]:
    try:
        probe = processes.FFProbe(path)
    except (KeyboardInterrupt, SystemExit) as sys_exit:
        raise SystemExit(130) from sys_exit
    except OSError as e:
        if e.errno == 23:  # Too many open files
            raise e
        raise e
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

    corruption = None
    if args.check_corrupt:
        corruption = media_check.calculate_corruption(path, chunk_size=args.chunk_size, gap=args.gap, full_scan=args.full_scan, threads=1)
        if args.delete_corrupt and corruption > (args.delete_corrupt / 100):
            file_utils.trash(path)
            return None

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

    def parse_framerate(string) -> Optional[float]:
        top, bot = string.split("/")
        bot = float(bot)
        if bot == 0:
            return None
        return float(top) / bot

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
        "duration": nums.safe_int(format_.pop("duration", None)),
        "language": language,
        "corruption": None if corruption is None else int(corruption * 100),
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
