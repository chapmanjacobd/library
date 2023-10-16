import platform, shlex, shutil, socket, subprocess
from pathlib import Path
from platform import system
from random import randrange
from shutil import which
from time import sleep
from typing import List, Optional, Tuple

from xklb import history
from xklb.media import subtitle
from xklb.post_actions import post_act
from xklb.utils import consts, devices, file_utils, iterables, path_utils, processes
from xklb.utils.consts import SC
from xklb.utils.log_utils import log


def calculate_duration(args, m) -> Tuple[int, int]:
    start = 0
    end = m.get("duration", 0)
    minimum_duration = 7 * 60
    playhead = m.get("playhead")
    if playhead:
        start = playhead

    duration = m.get("duration", 20 * 60)
    if args.start:
        if args.start.isnumeric() and int(args.start) > 0:
            start = int(args.start)
        elif "%" in args.start:
            start_percent = int(args.start[:-1])
            start = int(duration * start_percent / 100)
        elif playhead and any([end == 0, end > minimum_duration]):
            start = playhead
        elif args.start == "wadsworth":
            start = duration * 0.3
        else:
            start = int(args.start)
    if args.end:
        if args.end == "dawsworth":
            end = duration * 0.65
        elif "%" in args.end:
            end_percent = int(args.end[:-1])
            end = int(duration * end_percent / 100)
        elif "+" in args.end:
            end = int(args.start) + int(args.end)
        else:
            end = int(args.end)

    log.debug("calculate_duration: %s -- %s", start, end)
    return start, end


def get_browser() -> Optional[str]:
    default_application = processes.cmd("xdg-mime", "query", "default", "text/html").stdout
    return which(default_application.replace(".desktop", ""))


def find_xdg_application(media_file) -> Optional[str]:
    if media_file.startswith("http"):
        return get_browser()

    mimetype = processes.cmd("xdg-mime", "query", "filetype", media_file).stdout
    default_application = processes.cmd("xdg-mime", "query", "default", mimetype).stdout
    return which(default_application.replace(".desktop", ""))


def generic_player(args) -> List[str]:
    if platform.system() == "Linux":
        player = ["xdg-open"]
    elif any(p in platform.system() for p in ("Windows", "_NT-", "MSYS")):
        player = ["cygstart"] if shutil.which("cygstart") else ["start", ""]
    else:
        player = ["open"]
    args.player_need_sleep = True
    return player


def parse(args, m) -> List[str]:
    player = generic_player(args)
    mpv = which("mpv.com") or which("mpv") or "mpv"

    if args.override_player:
        player = [*args.override_player]
        args.player_need_sleep = False

    elif args.action in (SC.read) and m["path"]:
        player_path = find_xdg_application(m["path"])
        if player_path:
            args.player_need_sleep = False
            player = [player_path]

    elif mpv:
        args.player_need_sleep = False
        player = [mpv]
        if args.action in (SC.listen):
            player.extend([f"--input-ipc-server={args.mpv_socket}", "--no-video", "--keep-open=no", "--really-quiet"])
        elif args.action in (SC.watch):
            player.extend(["--force-window=yes", "--really-quiet"])

        if m["path"] and m["path"].startswith("http"):
            player.extend(["--script-opts=ytdl_hook-try_ytdl_first=yes"])

        if getattr(args, "multiple_playback", 1) < 2:
            player.extend(["--fs"])

        if args.loop:
            player.extend(["--loop-file=inf"])

        if getattr(args, "crop", None):
            player.extend(["--panscan=1.0"])

        if args.start:
            player.extend(["--no-save-position-on-quit"])

        if args.action == SC.watch and m and m.get("subtitle_count") is not None:
            if m["subtitle_count"] > 0:
                player.extend(args.player_args_sub)
            elif m["size"] > 500 * 1000000:  # 500 MB
                log.debug("Skipping subs player_args: size")
            else:
                player.extend(args.player_args_no_sub)

    elif system() == "Linux":
        player_path = find_xdg_application(m["path"])
        if player_path:
            args.player_need_sleep = False
            player = [player_path]

    if args.volume is not None:
        player.extend([f"--volume={args.volume}"])

    if args.action in (SC.watch, SC.listen, SC.search) and m:
        try:
            start, end = calculate_duration(args, m)
        except Exception:
            pass
        else:
            if end != 0:
                if start != 0:
                    player.extend([f"--start={start}"])
                if end != m["duration"]:
                    player.extend([f"--end={end}"])

    log.debug("player: %s", player)
    return player


def watch_chromecast(args, m: dict, subtitles_file=None) -> Optional[subprocess.CompletedProcess]:
    if "vlc" in args.player:
        catt_log = processes.cmd(
            "vlc",
            "--sout",
            "#chromecast",
            f"--sout-chromecast-ip={args.cc_ip}",
            "--demux-filter=demux_chromecast",
            "--sub-file=" + subtitles_file if subtitles_file else "",
            *args.player[1:],
            m["path"],
        )
    else:
        if args.action in (SC.watch, SC.listen):
            catt_log = processes.cmd(
                "catt",
                "-d",
                args.chromecast_device,
                "cast",
                "-s",
                subtitles_file if subtitles_file else consts.FAKE_SUBTITLE,
                m["path"],
            )
        else:
            catt_log = args.cc.play_url(m["path"], resolve=True, block=True)
    return catt_log


def listen_chromecast(args, player, m: dict) -> Optional[subprocess.CompletedProcess]:
    Path(consts.CAST_NOW_PLAYING).write_text(m["path"])
    Path(consts.FAKE_SUBTITLE).touch()
    catt = which("catt") or "catt"
    if args.cast_with_local:
        cast_process = subprocess.Popen(
            [catt, "-d", args.chromecast_device, "cast", "-s", consts.FAKE_SUBTITLE, m["path"]],
            **processes.os_bg_kwargs(),
        )
        sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
        # if pyChromecast provides a way to sync accurately that would be very interesting to know; I have not researched it
        processes.cmd_interactive(*player, "--", m["path"])
        catt_log = processes.Pclose(cast_process)  # wait for chromecast to stop (you can tell any chromecast to pause)
        sleep(3.0)  # give chromecast some time to breathe
    else:
        if m["path"].startswith("http"):
            catt_log = args.cc.play_url(m["path"], resolve=True, block=True)
        else:  #  local file
            catt_log = processes.cmd(catt, "-d", args.chromecast_device, "cast", "-s", consts.FAKE_SUBTITLE, m["path"])

    return catt_log


def socket_play(args, m: dict) -> None:
    # TODO: replace with python_mpv_jsonipc
    mpv = which("mpv") or "mpv"
    if args.sock is None:
        subprocess.Popen([mpv, "--idle", "--input-ipc-server=" + args.mpv_socket])
        while not Path(args.mpv_socket).exists():
            sleep(0.2)
        args.sock = socket.socket(socket.AF_UNIX)
        args.sock.connect(args.mpv_socket)

    start, end = calculate_duration(args, m)

    try:
        start = randrange(int(start), int(end - args.interdimensional_cable + 1))
        end = start + args.interdimensional_cable
    except Exception as e:
        log.info(e)
    if end == 0:
        return

    play_opts = f"start={start},save-position-on-quit=no,resume-playback=no"
    if args.action in (SC.listen):
        play_opts += ",video=no"
    elif args.action in (SC.watch):
        play_opts += ",fullscreen=yes,force-window=yes"

    if m["path"].startswith("http"):
        play_opts += ",script-opts=ytdl_hook-try_ytdl_first=yes"
    else:
        play_opts += ",really-quiet=yes"

    f = m["path"].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    args.sock.send((f'raw loadfile "{f}" replace "{play_opts}" \n').encode())
    sleep(args.interdimensional_cable)


def geom_walk(display, v=1, h=1) -> List[List[int]]:
    va = display.width // v
    ha = display.height // h

    geoms = []
    for v_idx in range(v):
        for h_idx in range(h):
            x = int(va * v_idx)
            y = int(ha * h_idx)
            log.debug("geom_walk %s", {"va": va, "ha": ha, "v_idx": v_idx, "h_idx": h_idx, "x": x, "y": y})
            geoms.append([va, ha, x, y])

    return geoms


def grid_stack(display, qty, swap=False) -> List[Tuple]:
    if qty == 1:
        return [("--fs", f'--screen-name="{display.name}"', f'--fs-screen-name="{display.name}"')]
    else:
        dv = list(iterables.divisor_gen(qty))
        if not dv:
            vh = (qty, 1)
            log.debug("not dv %s", {"dv": dv, "vh": vh})
        else:
            v = dv[len(dv) // 2]
            h = qty // v
            vh = (v, h)
            log.debug("dv %s", {"dv": dv, "vh": vh})

    v, h = vh
    if swap:
        h, v = v, h
    holes = geom_walk(display, v=v, h=h)
    return [(hole, f'--screen-name="{display.name}"') for hole in holes]


def get_display_by_name(displays, screen_name):  # noqa: ANN201; -> List[screeninfo.Monitor]
    for d in displays:
        if d.name == screen_name:
            return [d]

    display_names = '", "'.join([d.name for d in displays])
    msg = f'Display "{screen_name}" not found. I see: "{display_names}"'
    raise ValueError(msg)


def is_hstack(args, display) -> bool:
    if args.hstack or args.portrait:
        return True
    elif args.vstack:
        return False
    elif display.width > display.height:  # wide
        return False
    else:  # tall or square: prefer horizontal split
        return True


def modify_display_size_for_taskbar(display):
    try:
        if platform.system() == "Windows":
            import win32gui  # type: ignore

            taskbar_window_handle = win32gui.FindWindow("Shell_TrayWnd", None)
            if taskbar_window_handle == 0:
                taskbar_window_handle = win32gui.FindWindow("Shell_SecondaryTrayWnd", None)
            if taskbar_window_handle == 0:
                return display

            work_area = win32gui.GetMonitorInfo(taskbar_window_handle)["rcWork"]  # type: ignore

            _taskbar_height = display.height - work_area[3]
            display.height = work_area[3] - work_area[1]
            display.width = work_area[2] - work_area[0]

        elif platform.system() == "Linux":
            xprop_output = subprocess.check_output("xprop -root _NET_WORKAREA".split()).decode().strip()
            work_area = [int(x) for x in xprop_output.split(" = ")[1].split(",")]

            _taskbar_height = display.height - work_area[3]
            display.height = work_area[3] - work_area[1]
            display.width = work_area[2] - work_area[0]

        elif platform.system() == "Darwin":
            dock_height = int(subprocess.check_output(["defaults", "read", "com.apple.dock", "tilesize"]).strip())
            dock_position = (
                subprocess.check_output(["defaults", "read", "com.apple.dock", "orientation"]).decode().strip()
            )
            if dock_position == "left" or dock_position == "right":
                display.width -= dock_height
            else:
                display.height -= dock_height

        return display
    except Exception:
        return display


def get_multiple_player_template(args) -> List[str]:
    import screeninfo

    displays = screeninfo.get_monitors()
    if args.screen_name:
        displays = get_display_by_name(displays, args.screen_name)

    if args.multiple_playback == consts.DEFAULT_MULTIPLE_PLAYBACK and len(displays) == 1:
        args.multiple_playback = 2
    elif args.multiple_playback == consts.DEFAULT_MULTIPLE_PLAYBACK and len(displays) > 1:
        args.multiple_playback = len(displays)
    elif args.multiple_playback < len(displays):
        # play videos on supporting screens but not active one
        displays = [d for d in displays if not d.is_primary]
        displays = displays[: len(args.multiple_playback)]

    min_media_per_screen, remainder = divmod(args.multiple_playback, len(displays))

    if min_media_per_screen > 1:
        displays[0] = modify_display_size_for_taskbar(displays[0])

    displays.sort(key=lambda d: d.width * d.height, reverse=True)
    players = []
    for d_idx, display in enumerate(displays):
        qty = min_media_per_screen
        if remainder > 0 and d_idx == 0:
            qty += remainder

        players.extend(grid_stack(display, qty, swap=is_hstack(args, display)))

    log.debug(players)

    return players


def geom(x_size, y_size, x, y) -> str:
    return f"--geometry={x_size}x{y_size}+{x}+{y}"


def _create_player(args, player, window_geometry, media):
    m = media.pop()
    print(m["path"])
    mp_args = ["--window-scale=1", "--no-border", "--no-keepaspect-window"]
    return {
        **m,
        "process": subprocess.Popen(
            [*player, *mp_args, *window_geometry, "--", m["path"]],
            **processes.os_bg_kwargs(),
        ),
    }


def multiple_player(args, media) -> None:
    player = parse(args, media[0])

    template = get_multiple_player_template(args)
    players = []

    media.reverse()  # because media.pop()
    try:
        while media or players:
            for t_idx, t in enumerate(template):
                SINGLE_PLAYBACK = ("--fs", '--screen-name="eDP"', '--fs-screen-name="eDP"')
                if len(t) == len(SINGLE_PLAYBACK):
                    player_hole = t
                    geom_data = None
                else:  # MULTI_PLAYBACK = ([640, 1080, 0, 0], '--screen-name="eDP"')
                    geom_data, screen_name = t
                    player_hole = [geom(*geom_data), screen_name]

                try:
                    m = players[t_idx]
                except IndexError:
                    log.debug("%s IndexError", t_idx)
                    if media:
                        players.append(_create_player(args, player, player_hole, media))
                else:
                    log.debug("%s Check if still running", t_idx)
                    if m["process"].poll() is not None:
                        r = processes.Pclose(m["process"])
                        if r.returncode != 0:
                            log.warning("Player exited with code %s", r.returncode)
                            log.debug(shlex.join(r.args))
                            if not args.ignore_errors:
                                raise SystemExit(r.returncode)

                        history.add(args, [m["path"]], mark_done=True)
                        post_act(args, m["path"], geom_data=geom_data, media_len=len(media))

                        if media:
                            players[t_idx] = _create_player(args, player, player_hole, media)
                        else:
                            del players[t_idx]

            log.debug("%s media", len(media))
            sleep(0.2)  # I don't know if this is necessary but may as well~~
    finally:
        for m in players:
            m["process"].kill()


def local_player(args, player, m) -> subprocess.CompletedProcess:
    if args.folder:
        paths = [str(Path(m["path"]).parent)]
    elif args.folder_glob:
        paths = file_utils.fast_glob(Path(m["path"]).parent, args.folder_glob)
    else:
        paths = [m["path"]]

    if system() == "Windows" or args.action in (SC.watch):
        r = processes.cmd(*player, *paths, strict=False)
    else:  # args.action in (SC.listen)
        r = processes.cmd_interactive(*player, *paths)

    if args.player_need_sleep:
        try:
            devices.confirm("Continue?")
        except Exception:
            if hasattr(m, "duration"):
                delay = m["duration"]
            else:
                delay = 10  # TODO: idk
            sleep(delay)

    return r


def chromecast_play(args, player, m) -> None:
    if args.action in (SC.watch):
        catt_log = watch_chromecast(
            args,
            m,
            subtitles_file=iterables.safe_unpack(subtitle.get_subtitle_paths(m["path"])),
        )
    elif args.action in (SC.listen):
        catt_log = listen_chromecast(args, player, m)
    else:
        raise NotImplementedError

    if catt_log:
        if catt_log.stderr is None or catt_log.stderr == "":
            if not args.cast_with_local:
                raise RuntimeError("catt does not exit nonzero? but something might have gone wrong")
        elif "Heartbeat timeout, resetting connection" in catt_log.stderr:
            raise RuntimeError("Media is possibly partially unwatched")


def transcode(args, path) -> str:
    log.debug(path)
    sub_index = subtitle.get_sub_index(args, path)

    transcode_dest = str(Path(path).with_suffix(".mkv"))
    temp_video = path_utils.random_filename(transcode_dest)

    maps = ["-map", "0"]
    if sub_index:
        maps = ["-map", "0:v", "-map", "0:a", "-map", "0:" + str(sub_index), "-scodec", "webvtt"]

    video_settings = [
        "-vcodec",
        "h264",
        "-preset",
        "fast",
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-crf",
        "17",
        "-pix_fmt",
        "yuv420p",
    ]
    if args.transcode_audio:
        video_settings = ["-c:v", "copy"]

    print("Transcoding", temp_video)
    processes.cmd_interactive(
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-stats",
        "-i",
        path,
        *maps,
        *video_settings,
        "-acodec",
        "libopus",
        "-ac",
        "2",
        "-b:a",
        "128k",
        "-filter:a",
        "loudnorm=i=-18:lra=17",
        temp_video,
    )

    Path(path).unlink()
    shutil.move(temp_video, transcode_dest)
    with args.db.conn:
        args.db.conn.execute("UPDATE media SET path = ? where path = ?", [transcode_dest, path])
    return transcode_dest
