import argparse, os, platform
from pathlib import Path

from python_mpv_jsonipc import MPV

from xklb import consts, utils
from xklb.utils import cmd, log


def parse_args(action) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=f"library {action}")
    parser.add_argument("--mpv-socket", default=consts.DEFAULT_MPV_SOCKET)
    parser.add_argument("--chromecast-device", "--cast-to", "-t")

    if action == "next":
        parser.add_argument("--delete", action="store_true")

    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    if os.path.exists(args.mpv_socket):
        try:
            args.mpv = MPV(start_mpv=False, ipc_socket=args.mpv_socket)
        except ConnectionRefusedError:
            Path(args.mpv_socket).unlink(missing_ok=True)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def _now_playing(args) -> dict:
    media = {
        "catt": Path(consts.CAST_NOW_PLAYING).read_text() if os.path.exists(consts.CAST_NOW_PLAYING) else None,
        "mpv": args.mpv.command("get_property", "path") if os.path.exists(args.mpv_socket) else None,
    }
    log.info(media)
    return media


def print_now_playing(playing, source) -> None:
    if playing[source].startswith("http"):
        print(source, "\t", cmd("ffprobe", "-hide_banner", "-loglevel", "info", playing[source]).stderr)
    else:
        print(source, "\t", playing[source])


def playback_now() -> None:
    args = parse_args("now")
    playing = _now_playing(args)

    if playing["mpv"]:
        print_now_playing(playing, "mpv")
        args.mpv.terminate()

    if playing["catt"]:
        print_now_playing(playing, "catt")


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
    if any([p in platform.system() for p in ("Windows", "_NT-", "MSYS")]):
        cmd("taskkill", "/f", "/im", name, strict=False)
    else:
        cmd("pkill", "-f", name, strict=False)


def playback_stop() -> None:
    args = parse_args("stop")

    playing = _now_playing(args)
    if playing["mpv"]:
        args.mpv.command("loadfile", "/dev/null")  # make mpv exit with code 3

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
        if args.delete:
            utils.trash(playing["mpv"])
