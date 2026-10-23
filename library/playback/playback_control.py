import argparse, textwrap
from contextlib import suppress
from copy import deepcopy
from pathlib import Path

from library import usage
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    iterables,
    mpv_utils,
    nums,
    objects,
    printing,
    processes,
    shell_utils,
    strings,
)
from library.utils.log_utils import log

MIN_COVER_COMMENT_LENGTH = 15


def parse_args(usage, command=None) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage)
    if command == "next":
        arggroups.capability_delete(parser)
    if command in {"ffwd", "rewind", "seek"}:
        parser.add_argument("time")

    parser.add_argument("--mpv-socket", help="Use a custom mpv socket location")
    parser.add_argument("--chromecast-device", "--cast-to", "-t")

    arggroups.debug(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    args.mpv_socket, args.mpv = mpv_utils.connect_default_mpv(args.mpv_socket)

    return args


def _now_playing(args) -> dict:
    media = {
        "catt": Path(consts.CAST_NOW_PLAYING).read_text() if Path(consts.CAST_NOW_PLAYING).exists() else None,
        "mpv": args.mpv.command("get_property", "path") if Path(args.mpv_socket).exists() else None,
    }
    log.info(media)
    return media


def from_duration_to_duration_str(duration, segment_start, segment_end):
    if segment_start > duration and segment_end == 0:
        segment_end = segment_start + duration

    # TODO: this could probably be simplified to:
    # duration, end, start = sorted(...)
    if segment_start > segment_end > 0 and segment_start + segment_end > duration:
        segment_start, segment_end = segment_end, segment_start

    if segment_start or segment_end:
        if segment_end > 0:
            segment_duration = segment_end - segment_start
        else:
            segment_duration = duration - segment_start  # segment muxer copies original duration

        start_str = printing.seconds_to_hhmmss(segment_start).strip()
        end_str = printing.seconds_to_hhmmss(segment_end or duration).strip()
        duration_str = printing.seconds_to_hhmmss(segment_duration).strip()

        duration_str = f"Duration: {duration_str}"
        duration_str += f" ({start_str} to {end_str})"
    else:
        duration_str = printing.seconds_to_hhmmss(duration).strip()
        duration_str = f"Duration: {duration_str}"

    return duration_str


def _clean_probe_metadata(probe, path):
    excluded_keys = [
        "encoder",
        "major_brand",
        "minor_version",
        "compatible_brands",
        "software",
        "Segment-Durations-Ms",
        "play_count",
        "script",
        "barcode",
        "catalognumber",
        "isrc",
        "tsrc",
        "asin",
        "tlen",
        "tmed",
        "label",
        "media",
    ]
    excluded_key_like = [
        "duration",
        "musicbrainz",
        "acoustid",
        "release",
        "timestamp",
        "writing",
        "disc",
        "bps-",
        "number",
        "statistics",
        "language",
        "vendor",
        "handler",
        "publisher",
        "id3v2_priv",
        "replaygain_",
    ]

    tags = {k: v for d in [*probe.streams, probe.format] for k, v in d.get("tags", {}).items()}
    seen = set()
    metadata = objects.lower_keys(tags)
    for key, value in deepcopy(metadata).items():
        if key in excluded_keys or any(s in key for s in excluded_key_like) or value in seen or path in value:
            metadata.pop(key, None)
        seen.add(value)
    return metadata


def _probe_metadata_fields(metadata):
    comment = metadata.pop("comment", None) or ""
    if len(comment) < MIN_COVER_COMMENT_LENGTH and "cover" in comment.lower():
        comment = ""
    return {
        "description": iterables.safe_unpack(
            metadata.pop("description", None),
            metadata.pop("synopsis", None),
            metadata.pop("unsynced lyrics", None),
            metadata.pop("lyrics-none-eng", None),
            metadata.pop("songs-db_custom1", None),
            metadata.pop("songs-db_custom2", None),
            metadata.pop("songs-db_custom3", None),
            metadata.pop("songs-db_custom4", None),
            metadata.pop("songs-db_occasion", None),
            metadata.pop("albummood", None),
            comment if "http" not in comment else None,
        ),
        "genre": iterables.safe_unpack(
            metadata.pop("genre", None),
            metadata.pop("albumgenre", None),
            metadata.pop("albumgrouping", None),
        ),
        "artist": iterables.safe_unpack(
            metadata.pop("artist", None),
            metadata.pop("album_artist", None),
            metadata.pop("tso2", None),
            metadata.pop("performer", None),
            metadata.pop("artists", None),
            metadata.pop("composer", None),
        ),
        "album": iterables.safe_unpack(metadata.pop("album", None)),
        "track": iterables.safe_unpack(metadata.pop("track", None)),
        "track_total": iterables.safe_unpack(metadata.pop("tracktotal", None)),
        "title": iterables.safe_unpack(metadata.pop("title", None)),
        "url": iterables.safe_unpack(
            metadata.pop("purl", None),
            metadata.pop("url", None),
            comment if "http" in comment else None,
        ),
        "date": iterables.safe_unpack(
            metadata.pop("date", None),
            metadata.pop("time", None),
            metadata.pop("originalyear", None),
            metadata.pop("creation_time", None),
        ),
    }


def _format_probe_tags(fields):
    formatted_output = ""
    description = fields["description"]
    if description and not consts.MOBILE_TERMINAL:
        description = printing.wrap_paragraphs(description.strip(), width=100)
        formatted_output += f" Details: {textwrap.indent(description, '          ').lstrip()}\n"
    if fields["artist"]:
        formatted_output += f"  Artist: {fields['artist']}\n"
    if fields["album"]:
        formatted_output += f"   Album: {fields['album']}"
        if fields["track"]:
            track_total = f" of {fields['track_total']}" if fields["track_total"] else ""
            formatted_output += f" (track {fields['track']}{track_total})"
        formatted_output += "\n"
    if fields["title"]:
        formatted_output += f"   Title: {fields['title']}\n"
    if fields["genre"]:
        formatted_output += f"   Genre: {fields['genre']}\n"
    if fields["date"]:
        formatted_output += f"    Date: {fields['date']}\n"
    if fields["url"]:
        formatted_output += f"     URL: {fields['url']}\n"
    return formatted_output


def _format_probe_output(probe, fields, audio_count):
    formatted_output = ""
    if audio_count > 1:
        formatted_output += f"Audio tracks: {audio_count}\n"
    if len(probe.chapters) > 1:
        formatted_output += f"Chapters: {len(probe.chapters)}\n"
    formatted_output += _format_probe_tags(fields)

    duration = nums.safe_int(probe.duration) or 0
    if duration > 0:
        duration_str = from_duration_to_duration_str(
            duration,
            segment_start=nums.safe_int(probe.format.get("start_time")) or 0,
            segment_end=nums.safe_int(probe.format.get("end_time")) or 0,
        )
        formatted_output += duration_str
    return formatted_output


def reformat_ffprobe(path):
    try:
        probe = processes.FFProbe(path)
    except Exception:
        log.exception(f"Failed reading header. {path}")
        return path

    audio_count = sum(1 for stream in probe.streams if stream.get("codec_type") == "audio")
    metadata = _clean_probe_metadata(probe, path)
    fields = _probe_metadata_fields(metadata)
    formatted_output = _format_probe_output(probe, fields, audio_count)

    return textwrap.indent(formatted_output, "    ")


def now_playing(path) -> str:
    if path.startswith("http"):
        text = path
    else:
        text = path + "\n" + reformat_ffprobe(path)

    try:
        text.encode()
        return text
    except UnicodeEncodeError:
        try:
            text = path
            text.encode()
            return text
        except Exception:
            return "Could not encode file path as UTF-8"


def indent_prefix_first(text, prefix, indent="\t"):
    lines = text.splitlines()
    first_line = textwrap.indent(lines[0], prefix + indent) + "\n"
    rest_lines = textwrap.indent("\n".join(lines[1:]), indent)
    return first_line + rest_lines


def source_now_playing(playing, source) -> str:
    path = playing[source]
    text = indent_prefix_first(now_playing(path), prefix=source)
    return text


def playback_now() -> None:
    args = parse_args(usage.now)
    playing = _now_playing(args)

    if playing["mpv"] and playing["catt"]:
        print(source_now_playing(playing, "mpv"))
        with suppress(AttributeError):
            args.mpv.terminate(join=None)
        print(source_now_playing(playing, "catt"))

    elif playing["mpv"]:
        path = playing["mpv"]
        print(now_playing(path))
        time_pos = printing.seconds_to_hhmmss(args.mpv.command("get_property", "time-pos")).strip()
        print(f"    Playhead: {time_pos}\n")
        with suppress(AttributeError):
            args.mpv.terminate(join=None)

    elif playing["catt"]:
        path = playing["catt"]
        print(now_playing(path))

    else:
        log.error("Nothing seems to be playing. You may need to specify --mpv-socket or --chromecast-device")


def catt_stop(args) -> None:
    catt_device = []
    if args.chromecast_device:
        catt_device = ["-d", args.chromecast_device]
    processes.cmd("catt", *catt_device, "stop", strict=False)


def catt_pause(args) -> None:
    catt_device = []
    if args.chromecast_device:
        catt_device = ["-d", args.chromecast_device]
    processes.cmd("catt", *catt_device, "play_toggle", strict=False)


def kill_process(name) -> None:
    if consts.IS_WINDOWS:
        processes.cmd("taskkill", "/f", "/im", name, strict=False)
    else:
        processes.cmd("pkill", "-f", name, strict=False)


def playback_stop() -> None:
    args = parse_args(usage.stop)
    if args.simulate:
        print("Would stop playback")
        return

    playing = _now_playing(args)
    if playing["mpv"]:
        args.mpv.command("loadfile", "/dev/null")  # make mpv exit with code 3
        with suppress(AttributeError):
            args.mpv.terminate(join=None)

    if playing["catt"] or not any(playing.values()):
        kill_process("catt")
        catt_stop(args)

    Path(consts.CAST_NOW_PLAYING).unlink(missing_ok=True)
    Path(args.mpv_socket).unlink(missing_ok=True)


def playback_pause() -> None:
    args = parse_args(usage.pause)
    if args.simulate:
        print("Would pause playback")
        return

    playing = _now_playing(args)

    if playing["catt"]:
        catt_pause(args)

    if playing["mpv"]:
        args.mpv.command("cycle", "pause")
        with suppress(AttributeError):
            args.mpv.terminate(join=None)


def playback_next() -> None:
    args = parse_args(usage.next, command="next")
    if args.simulate:
        print("Would advance playback")
        return

    playing = _now_playing(args)

    # TODO: figure out if catt or mpv is stale
    # [kill_process(s) for s in ("python.*library", "bin/lb", "bin/library", "mpv")]
    if playing["catt"] or not any(playing.values()):
        Path(consts.CAST_NOW_PLAYING).unlink(missing_ok=True)
        catt_stop(args)
        if args.delete_files:
            shell_utils.trash(args, playing["catt"])

    if playing["mpv"]:
        args.mpv.command("playlist_next", "force")
        with suppress(AttributeError):
            args.mpv.terminate(join=None)
        if args.delete_files:
            shell_utils.trash(args, playing["mpv"])


def _seek_seconds(args, command):
    s = args.time
    is_relative = False
    is_negative = False
    if s.startswith("-"):
        is_negative = True
    if s.startswith(("+", "-")):
        is_relative = True
        s = s[1:]
    if ":" not in s:
        is_relative = True

    seconds = strings.from_timestamp_seconds(s) if ":" in s else float(s)
    if is_negative:
        seconds = -seconds
    if command == "rewind":
        is_relative = True
        is_negative = True
        seconds = -abs(seconds)
    elif command == "ffwd":
        is_relative = True
        is_negative = False
        seconds = abs(seconds)
    return seconds, is_relative, is_negative


def _seek_chromecast(args, seconds, is_relative, is_negative):
    catt_device = []
    if args.chromecast_device:
        catt_device = ["-d", args.chromecast_device]
    if is_relative and is_negative:
        processes.cmd("catt", *catt_device, "rewind", str(int(seconds)))
    elif is_relative:
        processes.cmd("catt", *catt_device, "ffwd", str(int(seconds)))
    else:
        processes.cmd("catt", *catt_device, "seek", str(int(seconds)))


def playback_seek(command="seek") -> None:
    args = parse_args(usage.seek, command=command)
    if args.simulate:
        print("Would seek playback by", args.time)
        return

    playing = _now_playing(args)
    seconds, is_relative, is_negative = _seek_seconds(args, command)

    if playing["mpv"]:
        args.mpv.command("seek", seconds, "relative" if is_relative else "absolute")
        with suppress(AttributeError):
            args.mpv.terminate(join=None)

    if playing["catt"]:
        _seek_chromecast(args, seconds, is_relative, is_negative)


def playback_ffwd() -> None:
    playback_seek(command="ffwd")


def playback_rewind() -> None:
    playback_seek(command="rewind")
