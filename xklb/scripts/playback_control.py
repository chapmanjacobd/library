import argparse, platform, textwrap
from copy import deepcopy
from pathlib import Path

import ffmpeg

from xklb import consts, utils
from xklb.utils import cmd, log


def parse_args(action) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=f"library {action}",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--mpv-socket", default=consts.DEFAULT_MPV_SOCKET)
    parser.add_argument("--chromecast-device", "--cast-to", "-t")

    if action == "next":
        parser.add_argument("--delete", action="store_true")

    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    args.mpv = utils.connect_mpv(args.mpv_socket)

    log.info(utils.dict_filter_bool(args.__dict__))

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
        probe = ffmpeg.probe(path, show_chapters=None)
    except Exception:
        log.exception(f"[{path}] Failed reading header. Metadata corruption")
        return path

    codec_types = [s.get("codec_type") for s in probe["streams"]]
    audio_count = sum(1 for s in codec_types if s == "audio")

    excluded_keys = ["encoder", "major_brand", "minor_version", "compatible_brands", "software"]

    seen = set()
    metadata = utils.lower_keys(probe["format"].get("tags", {}))
    for key, value in deepcopy(metadata).items():
        if key in excluded_keys or value in seen or path in value:
            metadata.pop(key, None)
        seen.add(value)

    description = utils.safe_unpack(
        metadata.pop("description", None),
        metadata.pop("synopsis", None),
    )
    artist = utils.safe_unpack(
        metadata.pop("artist", None),
    )
    title = utils.safe_unpack(
        metadata.pop("title", None),
    )
    url = utils.safe_unpack(
        metadata.pop("purl", None),
        metadata.pop("url", None),
        metadata.pop("comment", None),
    )
    date = utils.safe_unpack(
        metadata.pop("date", None),
        metadata.pop("time", None),
        metadata.pop("creation_time", None),
    )

    formatted_output = ""
    for key, value in metadata.items():
        formatted_output += f" {key} : {value.strip()}\n"

    if audio_count > 1:
        formatted_output += f"Audio tracks: {audio_count}\n"
    if len(probe["chapters"]) > 1:
        formatted_output += f"Chapters: {len(probe['chapters'])}\n"

    if date:
        formatted_output += f"    Date: {date}\n"
    if description and not consts.MOBILE_TERMINAL:
        description = utils.wrap_paragraphs(description.strip(), width=100)
        formatted_output += f"Description: \n{textwrap.indent(description, '          ')}\n"
    if artist:
        formatted_output += f"  Artist: {artist}\n"
    if url:
        formatted_output += f"     URL: {url}\n"
    if title:
        formatted_output += f"   Title: {title}\n"

    duration = utils.safe_int(probe["format"].get("duration")) or 0
    if duration > 0:
        duration_str = utils.seconds_to_hhmmss(duration).strip()
        formatted_output += f"Duration: {duration_str}\n"

        start = utils.safe_int(probe["format"].get("start_time")) or 0
        if start > 0:
            start_str = utils.seconds_to_hhmmss(start).strip()
            formatted_output += f"   Start: {start_str.rjust(len(duration_str) - len(start_str))}\n"

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
    cmd("catt", *catt_device, "stop")


def catt_pause(args) -> None:
    catt_device = []
    if args.chromecast_device:
        catt_device = ["-d", args.chromecast_device]
    cmd("catt", *catt_device, "play_toggle")


def kill_process(name) -> None:
    if any(p in platform.system() for p in ("Windows", "_NT-", "MSYS")):
        cmd("taskkill", "/f", "/im", name, strict=False)
    else:
        cmd("pkill", "-f", name, strict=False)


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
            utils.trash(playing["catt"])

    if playing["mpv"]:
        args.mpv.command("playlist_next", "force")
        args.mpv.terminate()
        if args.delete:
            utils.trash(playing["mpv"])
