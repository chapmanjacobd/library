import argparse, os, platform
from pathlib import Path

from python_mpv_jsonipc import MPV

from xklb import paths, utils
from xklb.utils import cmd, log


def parse_args(action):
    parser = argparse.ArgumentParser(prog=f"library {action}")
    parser.add_argument("--mpv-socket", default=paths.DEFAULT_MPV_SOCKET)
    parser.add_argument("--chromecast-device", "--cast-to", "-t")

    if action == "next":
        parser.add_argument("--delete", action="store_true")

    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    if os.path.exists(args.mpv_socket):
        args.mpv = MPV(start_mpv=False, ipc_socket=args.mpv_socket)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def _now_playing(args):
    media = {
        "catt": Path(paths.CAST_NOW_PLAYING).read_text() if os.path.exists(paths.CAST_NOW_PLAYING) else None,
        "mpv": args.mpv.command("get_property", "path") if os.path.exists(args.mpv_socket) else None,
    }
    log.info(media)
    if None not in media.values():
        log.warning("Both `catt` and `mpv` playback files found!")

    return media


def playback_now():
    args = parse_args("now")
    playing = _now_playing(args)

    if playing["mpv"]:
        print(
            "[mpv]:",
            cmd("ffprobe", "-hide_banner", "-loglevel", "info", playing["mpv"]).stderr
            if not playing["mpv"].startswith("http")
            else playing["mpv"],
        )
        args.mpv.terminate()
    if playing["catt"]:
        print(
            "[catt]:",
            cmd("ffprobe", "-hide_banner", "-loglevel", "info", playing["catt"]).stderr
            if not playing["catt"].startswith("http")
            else playing["catt"],
        )


def catt_stop(args):
    catt_device = []
    if args.chromecast_device:
        catt_device = ["-d", args.chromecast_device]
    cmd("catt", *catt_device, "stop")


def kill_process(name):
    if any([p in platform.system() for p in ["Windows", "_NT-", "MSYS"]]):
        cmd("taskkill", "/f", "/im", name)
    else:
        cmd("pkill", "-f", name)


def playback_stop():
    args = parse_args("stop")

    playing = _now_playing(args)
    if playing["mpv"]:
        args.mpv.command("loadfile", "/dev/null")  # make mpv exit with code 3
    else:
        [kill_process(s) for s in ["python.*xklb", "bin/lb", "bin/library", "mpv"]]

    if playing["catt"]:
        catt_stop(args)

    Path(paths.CAST_NOW_PLAYING).unlink(missing_ok=True)
    Path(args.mpv_socket).unlink(missing_ok=True)


def playback_next():
    args = parse_args("next")

    playing = _now_playing(args)

    # TODO: figure out if catt or mpv is stale
    if playing["catt"]:
        Path(paths.CAST_NOW_PLAYING).unlink(missing_ok=True)
        catt_stop(args)
        if args.delete:
            Path(playing["catt"]).unlink(missing_ok=True)

    if playing["mpv"]:
        args.mpv.command("playlist_next", "force")
        if args.delete:
            Path(playing["mpv"]).unlink(missing_ok=True)
