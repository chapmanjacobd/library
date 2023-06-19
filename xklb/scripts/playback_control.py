import argparse, platform, textwrap
from pathlib import Path

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


def now_playing(path) -> str:
    if path.startswith("http"):
        text = path
    else:
        text = (
            path
            + "\n"
            + "\n".join(
                line
                for line in cmd("ffprobe", "-hide_banner", "-loglevel", "info", path).stderr.splitlines()
                if path not in line
            )
            + "\n"
        )

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
