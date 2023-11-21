import argparse, platform, textwrap
from copy import deepcopy
from pathlib import Path

from xklb.utils import consts, file_utils, iterables, mpv_utils, nums, objects, printing, processes
from xklb.utils.log_utils import log


def parse_args(action) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=f"library {action}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--mpv-socket", default=consts.DEFAULT_MPV_LISTEN_SOCKET)
    parser.add_argument("--chromecast-device", "--cast-to", "-t")

    if action == "next":
        parser.add_argument(
            "--delete",
            "--remove",
            "--erase",
            "--rm",
            "-rm",
            action="store_true",
            help="Delete currently playing media",
        )

    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    args.mpv = mpv_utils.connect_mpv(args.mpv_socket)

    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def _now_playing(args) -> dict:
    media = {
        "catt": Path(consts.CAST_NOW_PLAYING).read_text() if Path(consts.CAST_NOW_PLAYING).exists() else None,
        "mpv": args.mpv.command("get_property", "path") if Path(args.mpv_socket).exists() else None,
    }
    log.info(media)
    return media


def reformat_ffprobe(path):
    try:
        probe = processes.FFProbe(path)
    except Exception:
        log.exception(f"Failed reading header. {path}")
        return path

    codec_types = [s.get("codec_type") for s in probe.streams]
    audio_count = sum(1 for s in codec_types if s == "audio")

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

    comment = metadata.pop("comment", None) or ""
    if len(comment) < 15 and "cover" in comment.lower():
        comment = ""
    description = iterables.safe_unpack(
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
    )
    genre = iterables.safe_unpack(
        metadata.pop("genre", None),
        metadata.pop("albumgenre", None),
        metadata.pop("albumgrouping", None),
    )
    artist = iterables.safe_unpack(
        metadata.pop("artist", None),
        metadata.pop("album_artist", None),
        metadata.pop("tso2", None),
        metadata.pop("performer", None),
        metadata.pop("artists", None),
        metadata.pop("composer", None),
    )
    album = iterables.safe_unpack(
        metadata.pop("album", None),
    )
    track = iterables.safe_unpack(
        metadata.pop("track", None),
    )
    track_total = iterables.safe_unpack(
        metadata.pop("tracktotal", None),
    )
    title = iterables.safe_unpack(
        metadata.pop("title", None),
    )
    url = iterables.safe_unpack(
        metadata.pop("purl", None),
        metadata.pop("url", None),
        comment if "http" in comment else None,
    )
    date = iterables.safe_unpack(
        metadata.pop("date", None),
        metadata.pop("time", None),
        metadata.pop("originalyear", None),
        metadata.pop("creation_time", None),
    )

    formatted_output = ""
    # for key, value in metadata.items():
    #     formatted_output += f"{key}::{value.strip()}\n"

    if audio_count > 1:
        formatted_output += f"Audio tracks: {audio_count}\n"
    if len(probe.chapters) > 1:
        formatted_output += f"Chapters: {len(probe.chapters)}\n"

    if description and not consts.MOBILE_TERMINAL:
        description = printing.wrap_paragraphs(description.strip(), width=100)
        formatted_output += f" Details: {textwrap.indent(description, '          ').lstrip()}\n"
    if artist:
        formatted_output += f"  Artist: {artist}\n"
    if album:
        formatted_output += f"   Album: {album}"
        if track:
            formatted_output += f" (track {track}{(' of ' + track_total) if track_total else ''})"
        formatted_output += "\n"
    if title:
        formatted_output += f"   Title: {title}\n"
    if genre:
        formatted_output += f"   Genre: {genre}\n"
    if date:
        formatted_output += f"    Date: {date}\n"
    if url:
        formatted_output += f"     URL: {url}\n"

    duration = nums.safe_int(probe.format.get("duration")) or 0
    if duration > 0:
        start = nums.safe_int(probe.format.get("start_time")) or 0
        if start > 0:
            total_duration = duration
            end = nums.safe_int(probe.format.get("end_time")) or 0
            if end > 0:
                duration = start - end
            else:
                duration -= start

            start_str = printing.seconds_to_hhmmss(start).strip()
            end_str = printing.seconds_to_hhmmss(end or total_duration).strip()
            duration_str = printing.seconds_to_hhmmss(duration).strip()

            formatted_output += f"Duration: {duration_str}"
            formatted_output += f" ({start_str} to {end_str})\n"
        else:
            duration_str = printing.seconds_to_hhmmss(duration).strip()
            formatted_output += f"Duration: {duration_str}\n"

    # print(cmd("ffprobe", "-hide_banner", "-loglevel", "info", path).stderr)
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
    args = parse_args("now")
    playing = _now_playing(args)

    if playing["mpv"] and playing["catt"]:
        print(source_now_playing(playing, "mpv"))
        args.mpv.terminate()
        print(source_now_playing(playing, "catt"))

    elif playing["mpv"]:
        path = playing["mpv"]
        print(now_playing(path))
        args.mpv.terminate()

    elif playing["catt"]:
        path = playing["catt"]
        print(now_playing(path))

    else:
        log.error("Nothing seems to be playing. You may need to specify --mpv-socket or --chromecast-device")


def catt_stop(args) -> None:
    catt_device = []
    if args.chromecast_device:
        catt_device = ["-d", args.chromecast_device]
    processes.cmd("catt", *catt_device, "stop")


def catt_pause(args) -> None:
    catt_device = []
    if args.chromecast_device:
        catt_device = ["-d", args.chromecast_device]
    processes.cmd("catt", *catt_device, "play_toggle")


def kill_process(name) -> None:
    if any(p in platform.system() for p in ("Windows", "_NT-", "MSYS")):
        processes.cmd("taskkill", "/f", "/im", name, strict=False)
    else:
        processes.cmd("pkill", "-f", name, strict=False)


def playback_stop() -> None:
    args = parse_args("stop")

    playing = _now_playing(args)
    if playing["mpv"]:
        args.mpv.command("loadfile", "/dev/null")  # make mpv exit with code 3
        args.mpv.terminate()

    if playing["catt"] or not any(playing.values()):
        kill_process("catt")
        catt_stop(args)

    Path(consts.CAST_NOW_PLAYING).unlink(missing_ok=True)
    Path(args.mpv_socket).unlink(missing_ok=True)


def playback_pause() -> None:
    args = parse_args("next")
    playing = _now_playing(args)

    if playing["catt"]:
        catt_pause(args)

    if playing["mpv"]:
        args.mpv.command("cycle", "pause")
        args.mpv.terminate()


def playback_next() -> None:
    args = parse_args("next")

    playing = _now_playing(args)

    # TODO: figure out if catt or mpv is stale
    # [kill_process(s) for s in ("python.*xklb", "bin/lb", "bin/library", "mpv")]
    if playing["catt"] or not any(playing.values()):
        Path(consts.CAST_NOW_PLAYING).unlink(missing_ok=True)
        catt_stop(args)
        if args.delete:
            file_utils.trash(playing["catt"])

    if playing["mpv"]:
        args.mpv.command("playlist_next", "force")
        args.mpv.terminate()
        if args.delete:
            file_utils.trash(playing["mpv"])
