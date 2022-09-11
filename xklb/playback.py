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

    if args.db:
        args.database = args.db

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
    print(_now_playing(args))


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

    [kill_process(s) for s in ["python.*xklb", "bin/lb", "bin/library", "mpv"]]
    Path(paths.CAST_NOW_PLAYING).unlink(missing_ok=True)

    catt_stop(args)
    args.mpv.command("quit")


def playback_next():
    args = parse_args("next")

    playing = _now_playing(args)

    if args.delete:
        # TODO: figure out if catt or mpv is stale
        for media in playing.values():
            Path(media).unlink()

    catt_stop(args)
    args.mpv.command("playlist_next", "force")
