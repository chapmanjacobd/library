import math, subprocess

from library.createdb import subtitle
from library.mediafiles import media_check
from library.utils import consts, date_utils, file_utils, iterables, nums, objects, path_utils, processes, strings
from library.utils.consts import DBType
from library.utils.log_utils import log


def get_subtitle_tags(path, streams, scan_subtitles=False) -> dict:
    attachment_count = sum(1 for s in streams if s.get("codec_type") == "attachment")
    internal_subtitles_count = sum(1 for s in streams if s.get("codec_type") == "subtitle")

    subtitles = []
    if scan_subtitles:
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


def parse_tags(mu: dict, ti: dict) -> dict:
    mu = objects.dumbcopy(mu)
    ti = objects.dumbcopy(ti)

    tags = {
        "mood": strings.combine(
            mu.pop("albummood", None),
            mu.pop("MusicMatch_Situation", None),
            mu.pop("Songs-DB_Occasion", None),
            mu.pop("albumgrouping", None),
        ),
        "genre": strings.combine(mu.pop("genre", None), ti.pop("genre", None), mu.pop("albumgenre", None)),
        "time_created": date_utils.specific_date(
            strings.combine(mu.pop("originalyear", None)),
            strings.combine(mu.pop("TDOR", None)),
            strings.combine(mu.pop("TORY", None)),
            strings.combine(mu.pop("date", None)),
            strings.combine(mu.pop("TDRC", None)),
            strings.combine(mu.pop("TDRL", None)),
            strings.combine(ti.pop("year", None)),
        ),
        "bpm": nums.safe_int(
            iterables.safe_unpack(mu.pop("fBPM", None), mu.pop("bpm", None), mu.pop("bpm_start", None))
        ),
        "key": iterables.safe_unpack(
            mu.pop("TIT1", None), mu.pop("key", None), mu.pop("TKEY", None), mu.pop("key_start", None)
        ),
        "decade": iterables.safe_unpack(mu.pop("Songs-DB_Custom1", None)),
        "categories": iterables.safe_unpack(mu.pop("Songs-DB_Custom2", None)),
        "city": iterables.safe_unpack(mu.pop("Songs-DB_Custom3", None)),
        "country": strings.combine(
            mu.pop("Songs-DB_Custom4", None),
            mu.pop("MusicBrainz Album Release Country", None),
            mu.pop("musicbrainz album release country", None),
            mu.pop("language", None),
        ),
        "description": strings.combine(
            mu.pop("description", None),
            mu.pop("synopsis", None),
            mu.pop("lyrics", None),
            mu.pop("publisher", None),
            mu.pop("comment", None),
            ti.pop("comment", None),
        ),
        "album": iterables.safe_unpack(ti.pop("album", None), mu.pop("album", None)),
        "title": iterables.safe_unpack(ti.pop("title", None), mu.pop("title", None)),
        "artist": strings.combine(
            ti.pop("artist", None),
            mu.pop("artist", None),
            mu.pop("artists", None),
            ti.pop("albumartist", None),
            ti.pop("composer", None),
        ),
    }

    mu = {k: v for k, v in mu.items() if not (k in consts.MEDIA_KNOWN_KEYS or v is None)}
    if mu != {}:
        log.debug("Extra av data %s", mu)
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


def collect_codecs(streams):
    from yt_dlp.utils import traverse_obj

    return ",".join(
        iterables.ordered_set(
            iterables.conform(s.get("codec_name") or traverse_obj(s, ["tags", "mimetype"]) for s in streams)
        )
    )


def munge_av_tags(args, m) -> dict:
    path = m["path"]
    try:
        probe = processes.FFProbe(path)
    except (KeyboardInterrupt, SystemExit) as sys_exit:
        raise SystemExit(130) from sys_exit
    except (TimeoutError, subprocess.TimeoutExpired):
        log.error(f"FFProbe timed out. {path}")
        m["error"] = "FFProbe timed out"
        return m
    except OSError as e:
        if e.errno == 23:  # Too many open files
            raise e
        elif e.errno == 5:  # IO Error
            raise e
        raise
    except processes.UnplayableFile as e:
        log.error(f"Failed reading header. {path}")
        log.debug(e)
        if (
            getattr(args, "delete_unplayable", False)
            and not path.startswith("http")
            and not file_utils.is_file_open(path)
        ):
            file_utils.trash(args, path, detach=False)
            m["time_deleted"] = consts.APPLICATION_START
        m["error"] = "Metadata check failed"
        return m

    if not probe.format:
        log.error(f"Failed reading format. {path}")
        log.warning(probe)
        return m

    format_ = probe.format
    size = format_.pop("size", None)
    bitrate_bps = format_.pop("bit_rate", None)
    format_.pop("format_name", None)
    format_.pop("format_long_name", None)
    format_.pop("nb_programs", None)
    format_.pop("nb_streams", None)
    format_.pop("nb_stream_groups", None)
    format_.pop("probe_score", None)
    format_.pop("start_time", None)
    format_.pop("filename", None)
    format_.pop("duration", None)
    duration = probe.duration

    if not m.get("size"):
        if size:
            m["size"] = int(size)
        elif bitrate_bps and duration:
            total_bits = duration * float(bitrate_bps)
            total_bytes = math.ceil(total_bits / 8)
            m["size"] = total_bytes

    corruption = None
    if getattr(args, "check_corrupt", False) and path_utils.ext(path) not in consts.SKIP_MEDIA_CHECK:
        try:
            corruption = media_check.calculate_corruption(
                path,
                chunk_size=args.chunk_size,
                gap=args.gap,
                full_scan=args.full_scan,
                full_scan_if_corrupt=args.full_scan_if_corrupt,
                threads=1,
            )
        except Exception:
            print(path)
            raise

        if media_check.corruption_threshold_exceeded(
            args.delete_corrupt, corruption, duration
        ) and not file_utils.is_file_open(path):
            threshold_str = (
                strings.percent(args.delete_corrupt) if 0 < args.delete_corrupt < 1 else (args.delete_corrupt + "s")
            )
            log.warning("Deleting %s corruption %.1f%% exceeded threshold %s", path, corruption * 100, threshold_str)
            file_utils.trash(args, path, detach=False)
            m["time_deleted"] = consts.APPLICATION_START
            m["error"] = "Media check failed"

    tags = format_.pop("tags", None)
    if tags:
        tags = objects.dict_filter_bool(
            {
                "title": tags.pop("title", None),
                "webpath": tags.pop("PURL", None),
                **{k: v for k, v in parse_tags(tags, tags).items() if v},
            },
        )

    if format_ != {}:
        log.info("Extra data %s", format_)

    streams = probe.streams

    width = iterables.safe_unpack([s.get("width") for s in streams])
    height = iterables.safe_unpack([s.get("height") for s in streams])

    stream_tags = [s.get("tags") for s in streams if s.get("tags") is not None]
    language = strings.combine(
        [t.get("language") for t in stream_tags if t.get("language") not in (None, "und", "unk")],
    )

    album_art_count = len(probe.album_art_streams)
    video_count = len(probe.video_streams)
    audio_count = len(probe.audio_streams)
    other_count = len(probe.other_streams)

    video_codecs = collect_codecs(probe.video_streams)
    audio_codecs = collect_codecs(probe.audio_streams)
    subtitle_codecs = collect_codecs(probe.subtitle_streams)
    other_codecs = collect_codecs(probe.other_streams)

    chapters = probe.chapters or []
    chapter_count = len(chapters)
    if chapter_count > 0:
        chapters = [
            {"time": int(float(d["start_time"])), "text": d["tags"]["title"]}
            for d in chapters
            if "tags" in d and "title" in d["tags"] and not strings.is_generic_title(d["tags"]["title"])
        ]

    m = {
        **m,
        "video_codecs": video_codecs,
        "audio_codecs": audio_codecs,
        "subtitle_codecs": subtitle_codecs,
        "other_codecs": other_codecs,
        "album_art_count": album_art_count,
        "video_count": video_count,
        "audio_count": audio_count,
        "chapter_count": chapter_count,
        "other_count": other_count,
        "width": width,
        "height": height,
        "fps": probe.fps,
        "duration": nums.safe_int(duration),
        "language": language,
        "corruption": None if corruption is None else int(corruption * 100),
        **(tags or {}),
        "chapters": chapters,
    }

    if m.get("time_deleted"):
        return m

    if objects.is_profile(args, DBType.video):
        video_tags = get_subtitle_tags(path, streams, scan_subtitles=getattr(args, "scan_subtitles", False))
        m = {**m, **video_tags}
    elif objects.is_profile(args, DBType.audio) and not str(path).startswith("http"):
        stream_tags = get_audio_tags(path)
        stream_tags = {k: v for k, v in stream_tags.items() if v}
        m = {**m, **stream_tags}

    return m
