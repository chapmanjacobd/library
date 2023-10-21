import hashlib, random, time
from pathlib import Path
from typing import Optional

from xklb.utils import nums
from xklb.utils.log_utils import log


def path_to_mpv_watchlater_md5(path: str) -> str:
    return hashlib.md5(path.encode("utf-8")).hexdigest().upper()


def mpv_watchlater_value(path, key) -> Optional[str]:
    data = Path(path).read_text().splitlines()
    for s in data:
        if s.startswith(key + "="):
            return s.split("=")[1]
    return None


def connect_mpv(ipc_socket, start_mpv=False):  # noqa: ANN201
    try:
        from python_mpv_jsonipc import MPV

        return MPV(start_mpv, ipc_socket)
    except (ConnectionRefusedError, FileNotFoundError):
        Path(ipc_socket).unlink(missing_ok=True)

    return None


def auto_seek(x_mpv, delay=0.0):
    x_mpv.wait_for_property("duration")
    time.sleep(delay)
    while True:
        wait = random.uniform(0.12, 0.18)
        for _ in range(10):
            x_mpv.command("no-osd", "seek", "4")
            time.sleep(wait)
        x_mpv.command("seek", str(random.uniform(0.2, 4)), "relative-percent")
        time.sleep(random.uniform(0.8, 1.2))


def get_playhead(
    args,
    path: str,
    start_time: float,
    existing_playhead: Optional[int] = None,
    media_duration: Optional[int] = None,
) -> Optional[int]:
    end_time = time.time()
    session_duration = int(end_time - start_time)
    python_playhead = session_duration
    if existing_playhead:
        python_playhead += existing_playhead

    md5 = path_to_mpv_watchlater_md5(path)
    metadata_path = Path(args.watch_later_directory, md5)
    try:
        mpv_playhead = nums.safe_int(mpv_watchlater_value(metadata_path, "start"))
    except Exception:
        mpv_playhead = None

    log.debug("mpv_playhead %s", mpv_playhead)
    log.debug("python_playhead %s", python_playhead)
    for playhead in [mpv_playhead or 0, python_playhead]:
        if playhead > 0 and (media_duration is None or media_duration >= playhead):
            return playhead
    return None


def mpv_cli_args_to_pythonic(arg_strings):
    arg_dict = {}
    for s in arg_strings:
        for arg in s.split(","):
            k, v = arg.lstrip("-").split("=")
            arg_dict[k] = v
    return arg_dict
