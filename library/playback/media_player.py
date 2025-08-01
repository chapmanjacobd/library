import os, shutil, subprocess, threading, time
from argparse import Namespace
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from platform import system
from random import randrange
from shutil import which
from time import sleep

from library.createdb import subtitle
from library.mediadb import db_history, db_media
from library.playback import playback_control, post_actions
from library.utils import consts, db_utils, devices, iterables, log_utils, mpv_utils, path_utils, processes
from library.utils.consts import SC
from library.utils.log_utils import log


def watch_chromecast(args, m: dict, subtitles_file=None) -> subprocess.CompletedProcess | None:
    if "vlc" in m["player"]:
        subtitles = ["--sub-file=" + subtitles_file] if subtitles_file else []
        catt_log = processes.cmd(
            "vlc",
            "--sout",
            "#chromecast",
            f"--sout-chromecast-ip={args.cc_ip}",
            "--demux-filter=demux_chromecast",
            *subtitles,
            *m["player"][1:],
            m["path"],
        )
    elif args.action in (SC.watch, SC.listen):
        subtitles = ["-s", subtitles_file] if subtitles_file else ["--no-subs"]
        catt_log = processes.cmd(
            "catt",
            "-d",
            args.chromecast_device,
            "cast",
            *subtitles,
            m["path"],
        )
    else:
        catt_log = args.cc.play_url(m["path"], resolve=True, block=True)
    return catt_log


def calculate_duration(args, m) -> tuple[int, int]:
    start = 0
    end = m.get("duration") or 0

    if args.interdimensional_cable:
        start = randrange(int(start), int(end - args.interdimensional_cable + 1))
        end = start + args.interdimensional_cable
        log.debug("calculate_duration: %s -- %s", start, end)
        return start, end

    minimum_duration = 7 * 60
    playhead = m.get("playhead")
    if playhead:
        start = playhead

    duration = m.get("duration", 20 * 60)
    if args.start:
        if args.start.isnumeric() and int(args.start) > 0:
            start = int(args.start)
        elif "%" in args.start:
            start_percent = int(args.start.rstrip("%"))
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
            end_percent = int(args.end.rstrip("%"))
            end = int(duration * end_percent / 100)
        elif "+" in args.end:
            end = int(args.start) + int(args.end)
        else:
            end = int(args.end)

    log.debug("calculate_duration: %s -- %s", start, end)
    return start, end


def listen_chromecast(args, m: dict) -> subprocess.CompletedProcess | None:
    Path(consts.CAST_NOW_PLAYING).write_text(m["path"])
    catt = which("catt") or "catt"
    start, end = calculate_duration(args, m)

    if args.cast_with_local:
        cast_process = subprocess.Popen(
            [
                catt,
                "-d",
                args.chromecast_device,
                "cast",
                "--no-subs",
                "--block",
                "--seek-to",
                str(start),
                m["path"],
            ],
            **processes.os_bg_kwargs(),
        )
        sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
        # if pyChromecast provides a way to sync accurately that would be very interesting to know; I have not researched it
        processes.cmd_interactive(*m["player"], "--", m["path"])
        catt_log = processes.Pclose(cast_process)  # wait for chromecast to stop (you can tell any chromecast to pause)
        sleep(3.0)  # give chromecast some time to breathe
    elif m["path"].startswith("http"):
        catt_log = args.cc.play_url(m["path"], resolve=True, block=True)
    else:  #  local file
        catt_log = processes.cmd(
            catt,
            "-d",
            args.chromecast_device,
            "cast",
            "--no-subs",
            "--block",
            "--seek-to",
            str(start),
            m["path"],
        )

    return catt_log


def chromecast_play(args, m) -> None:
    if args.action in (SC.watch):
        catt_log = watch_chromecast(
            args,
            m,
            subtitles_file=iterables.safe_unpack(subtitle.get_subtitle_paths(m["path"])),
        )
    elif args.action in (SC.listen):
        catt_log = listen_chromecast(args, m)
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
        "-c:v",
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
    r = processes.cmd_interactive(
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stats",
        "-i",
        path,
        *maps,
        *video_settings,
        "-c:a",
        "libopus",
        "-ac",
        "2",
        "-b:a",
        "128k",
        "-filter:a",
        "loudnorm=i=-18:lra=17",
        temp_video,
    )

    if Path(temp_video).exists():
        Path(path).unlink()
        shutil.move(temp_video, transcode_dest)
        with args.db.conn:
            args.db.conn.execute("UPDATE media SET path = ? where path = ?", [transcode_dest, path])
        return transcode_dest
    else:
        return path


def get_browser() -> str | None:
    default_application = processes.cmd("xdg-mime", "query", "default", "text/html").stdout
    return which(default_application.replace(".desktop", ""))


def find_xdg_application(media_file) -> str | None:
    if media_file.startswith("http"):
        return get_browser()

    mimetype = processes.cmd("xdg-mime", "query", "filetype", media_file).stdout
    default_application = processes.cmd("xdg-mime", "query", "default", mimetype).stdout
    return which(default_application.replace(".desktop", ""))


def generic_player() -> list[str]:
    if consts.IS_LINUX:
        player = ["xdg-open"]
    elif consts.IS_WINDOWS:
        player = ["cygstart"] if shutil.which("cygstart") else ["start", ""]
    else:
        player = ["open"]
    return player


def geom_walk(display, v=1, h=1) -> list[list[int]]:
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


def grid_stack(display, qty, swap=False) -> list[tuple]:
    if qty == 1:
        return [("--fs", f'--screen-name="{display.name}"', f'--fs-screen-name="{display.name}"')]
    else:
        dv = sorted(iterables.divisors_upto_sqrt(qty))
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
        if consts.IS_WINDOWS:
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

        elif consts.IS_LINUX:
            xprop_output = subprocess.check_output("xprop -root _NET_WORKAREA".split()).decode().strip()
            work_area = [int(x) for x in xprop_output.split(" = ")[1].split(",")]

            _taskbar_height = display.height - work_area[3]
            display.height = work_area[3] - work_area[1]
            display.width = work_area[2] - work_area[0]

        elif consts.IS_MAC:
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


def get_multiple_player_template(args) -> list[tuple[str, str]]:
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
        displays = displays[: args.multiple_playback]

    min_media_per_screen, remainder = divmod(args.multiple_playback, len(displays))

    if min_media_per_screen > 1:
        displays[0] = modify_display_size_for_taskbar(displays[0])

    displays.sort(key=lambda d: d.width * d.height, reverse=True)
    players = []
    for d_idx, display in enumerate(displays):
        qty = min_media_per_screen
        if remainder > 0 and d_idx == 0:
            qty += remainder

        grids = grid_stack(display, qty, swap=is_hstack(args, display))
        if args.fstack and qty > 1:
            players.extend(
                [("--fs", f'--screen-name="{display.name}"', f'--fs-screen-name="{display.name}"') for _ in grids]
            )
        else:
            players.extend(grids)

    log.debug(players)

    return players


class MediaPrefetcher:
    def __init__(self, args, media: list[dict]):
        self.args = Namespace(**{k: v for k, v in args.__dict__.items() if k not in {"db"}})
        self.media = media
        self.media.reverse()
        self.remaining = len(media)
        self.ignore_paths = set()
        self.futures = deque()

    def fetch(self):
        if self.media:
            with ThreadPoolExecutor(max_workers=1) as executor:
                fill_count = 0
                while self.media and len(self.futures) < max(1, self.args.prefetch):
                    m = self.media.pop()
                    if m["path"] in self.ignore_paths:
                        continue

                    future = executor.submit(self.prep_media, m)  # if self.args.prefetch > 1 else []
                    self.ignore_paths.add(m["path"])
                    self.futures.append(future)
                    fill_count += 1
                log.debug("prefetch full (inserted %s)", fill_count)
        return self

    def infer_command(self, m) -> tuple[list[str], bool]:
        args = self.args

        player = generic_player()
        player_need_sleep = True

        if getattr(args, "override_player", False):
            player = [*args.override_player]
            player_need_sleep = False

        elif getattr(args, "folders", False):
            player_need_sleep = True

        elif args.action in (SC.read):
            if system() == "Linux":
                player_path = find_xdg_application(m["path"])
                if player_path:
                    player_need_sleep = False
                    player = [player_path]

        else:
            mpv = which("mpv.com") or which("mpv")
            if mpv:
                player_need_sleep = False
                player = [mpv]
                if args.action in (SC.listen):
                    player.extend(
                        [f"--input-ipc-server={args.mpv_socket}", "--video=no", "--keep-open=no", "--really-quiet=yes"]
                    )
                elif args.action in (SC.watch):
                    player.extend(["--force-window=yes", "--really-quiet=yes"])

                if args.fullscreen:
                    player.extend(["--fullscreen=yes"])
                elif args.fullscreen is False:
                    player.extend(["--fullscreen=no"])

                if getattr(args, "loop", False):
                    player.extend(["--loop-file=inf"])

                if getattr(args, "pause", False):
                    player.extend(["--pause=yes"])

                if getattr(args, "crop", None):
                    player.extend(["--panscan=1.0"])

                if getattr(args, "start", False):
                    player.extend(["--save-position-on-quit=no"])

                if args.action == SC.watch and m.get("subtitle_count") is not None:
                    if m["subtitle_count"] > 0:
                        player.extend(args.player_args_sub)
                    elif m["size"] > 500 * 1000000:  # 500 MB
                        log.debug("Skipping subs player_args: size")
                    else:
                        player.extend(args.player_args_no_sub)

                if getattr(args, "volume", None) is not None:
                    player.extend([f"--volume={args.volume}"])

                if getattr(args, "mute", False):
                    player.extend(["--mute"])

                if m["path"] and m["path"].startswith("http"):
                    player.extend(["--script-opts=ytdl_hook-try_ytdl_first=yes"])

                if args.action in (SC.watch, SC.listen, SC.search):
                    try:
                        start, end = calculate_duration(args, m)
                    except Exception as e:
                        log.info(e)
                    else:
                        if end != 0:
                            if start != 0:
                                player.extend([f"--start={start}"])
                            if end != m["duration"]:
                                player.extend([f"--end={end}"])

                if getattr(args, "interdimensional_cable", False):
                    player.extend(["--save-position-on-quit=no", "--resume-playback=no"])

        log.debug("player: %s", player)
        return player, player_need_sleep

    def prep_media(self, m: dict):
        t = log_utils.Timer()
        self.args.db = db_utils.connect(self.args)

        m["original_path"] = m["path"]
        if not m["path"].startswith("http"):
            media_path = Path(self.args.prefix + m["path"]).resolve() if self.args.prefix else Path(m["path"])
            m["path"] = str(media_path)

            if not m["path"].startswith("http") and not media_path.exists():
                log.warning("[%s]: Does not exist. Skipping...", m["path"])
                db_media.mark_media_deleted(self.args, m["original_path"])
                return {}

            if self.args.transcode or self.args.transcode_audio:
                m["path"] = m["original_path"] = transcode(self.args, m["path"])
                log.debug("transcode: %s", t.elapsed())

        if self.args.folders:
            m["now_playing"] = m["path"]
        else:
            m["now_playing"] = playback_control.now_playing(m["path"]) + "\n"
        log.debug("playback_control: %s", t.elapsed())

        m["player"], m["player_need_sleep"] = self.infer_command(m)
        log.debug("player.parse: %s", t.elapsed())

        return m

    def get_m(self):
        m = None
        while m is None:
            if not self.futures:
                self.remaining = 0
                return None

            f = self.futures.popleft()
            f = f.result()
            if f is None:
                self.remaining = 0
                return None
            elif f == {}:
                self.fetch()
                continue

            if f["path"].startswith("http") or Path(f["path"]).exists():
                m = f
            else:
                self.fetch()

        self.remaining = len(self.media) + len(self.futures)
        self.fetch()
        return m


def single_player(args, m):
    is_windows = system() == "Windows"

    if args.folders:
        if args.override_player:
            r = processes.cmd(*m["player"], m["path"], strict=False)
        elif is_windows:
            os.startfile(m["path"])  # type: ignore
        elif which("open"):
            r = processes.cmd("open", m["path"], strict=False)
        else:
            r = processes.cmd("xdg-open", m["path"], strict=False)
    elif is_windows or args.action in (SC.watch):
        r = processes.cmd(*m["player"], m["path"], strict=False)
    else:  # args.action in (SC.listen)
        r = processes.cmd_interactive(*m["player"], m["path"], strict=False)

    if m["player_need_sleep"]:
        try:
            if not devices.confirm("Continue?"):
                raise SystemExit(0)
        except Exception:
            log.exception("Could not open prompt")
            delay = 10  # TODO: idk
            sleep(delay)
    return r


def _create_window_player(args, window_geometry, m):
    print(m["path"])
    m["player"].extend(window_geometry)
    return {
        **m,
        "process": subprocess.Popen(
            [*m["player"], "--", m["path"]],
            **processes.os_bg_kwargs(),
        ),
    }


def multiple_player(args, playlist) -> None:
    template = get_multiple_player_template(args)
    players = []

    try:
        while playlist.remaining or players:
            for t_idx, t in enumerate(template):
                SINGLE_PLAYBACK = ("--fs=yes", '--screen-name="eDP"', '--fs-screen-name="eDP"')
                if len(t) == len(SINGLE_PLAYBACK):
                    window_geometry = t
                    geom_data = None
                else:  # MULTI_PLAYBACK = ([640, 1080, 0, 0], '--screen-name="eDP"')
                    geom_data, screen_name = t
                    x_size, y_size, x, y = geom_data
                    window_geometry = [f"--geometry={x_size}x{y_size}+{x}+{y}", screen_name]

                window_geometry = ["--window-scale=1", "--no-border", "--no-keepaspect-window", *window_geometry]

                try:
                    m = players[t_idx]
                except IndexError:
                    log.debug("%s IndexError", t_idx)
                    m = playlist.get_m()
                    if m:
                        players.append(_create_window_player(args, window_geometry, m))
                else:
                    log.debug("%s Check if still running", t_idx)
                    if m["process"].poll() is not None:
                        player_process = processes.Pclose(m["process"])

                        post_actions.post_act(
                            args,
                            m["path"],
                            media_len=playlist.remaining,
                            geom_data=geom_data,
                            player_process=player_process,
                        )

                        m = playlist.get_m()
                        if m:
                            players[t_idx] = _create_window_player(args, window_geometry, m)
                        else:
                            del players[t_idx]

            log.debug("%s media", playlist.remaining)
            sleep(0.02)  # may as well~~
    finally:
        for m in players:
            m["process"].kill()


def mpv_jsonipc(args, m):
    from python_mpv_jsonipc import MPV, MPVError

    mpv_cli_args = m["player"][1:]
    mpv_kwargs = mpv_utils.mpv_cli_args_to_pythonic(mpv_cli_args)
    x_mpv = MPV(args.mpv_socket, log_handler=print, **mpv_kwargs)

    if args.volume:
        x_mpv.volume = args.volume

    SIGINT_EXIT = threading.Event()

    @x_mpv.on_key_press("ctrl+c")
    def sig_interrupt_handler():
        SIGINT_EXIT.set()
        x_mpv.command("quit", "4")

    x_mpv.play(m["path"])
    if args.auto_seek:
        try:
            mpv_utils.auto_seek(x_mpv)
        except (BrokenPipeError, MPVError, ConnectionResetError):
            log.debug("BrokenPipeError ignored")
    else:
        raise NotImplementedError
        # x_mpv.wait_for_property('idle-active')

    if SIGINT_EXIT.is_set():
        log.error("Player exited with code 4")
        raise SystemExit(4)


def play(args, m, media_len) -> None:
    t = log_utils.Timer()
    print(m["now_playing"])

    start_time = time.time()
    try:
        if args.chromecast:
            try:
                chromecast_play(args, m)
                t.reset()
                post_actions.post_act(args, m["original_path"], media_len=media_len)
                log.debug("player.post_act: %s", t.elapsed())
            except Exception:
                if args.ignore_errors:
                    return
                else:
                    raise
        elif args.auto_seek and Path(m["player"][0]).name in ["mpv", "mpv.com"]:
            mpv_jsonipc(args, m)
            post_actions.post_act(args, m["original_path"], media_len=media_len)
        else:
            player_process = single_player(args, m)
            t.reset()
            post_actions.post_act(args, m["original_path"], media_len=media_len, player_process=player_process)
            log.debug("player.post_act: %s", t.elapsed())
    finally:
        playhead = mpv_utils.get_playhead(
            args,
            m["original_path"],
            start_time,
            existing_playhead=m.get("playhead") or 0,
            media_duration=m.get("duration"),
        )
        log.debug("save_playhead %s", playhead)
        if playhead and args.db:
            db_history.add(args, [m["original_path"]], playhead=playhead)


def play_list(args, media):
    try:
        playlist = MediaPrefetcher(args, media)
        playlist.fetch()

        if args.multiple_playback > 1:
            multiple_player(args, playlist)
        else:
            while playlist.remaining:
                m = playlist.get_m()
                if m:
                    play(args, m, playlist.remaining)

    finally:
        Path(args.mpv_socket).unlink(missing_ok=True)
        if args.chromecast:
            Path(consts.CAST_NOW_PLAYING).unlink(missing_ok=True)
