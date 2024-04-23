import functools, json, multiprocessing, os, platform, shlex, signal, subprocess, sys
from typing import NoReturn

from xklb.utils import consts, iterables
from xklb.utils.log_utils import log


def exit_nicely(_signal, _frame) -> NoReturn:
    log.warning("\nExiting... (Ctrl+C)")
    raise SystemExit(130)


signal.signal(signal.SIGINT, exit_nicely)


def no_media_found() -> NoReturn:
    log.error("No media found")
    raise SystemExit(2)


def player_exit(completed_process) -> NoReturn:
    log.error("Player exited with code %s", completed_process.returncode)
    log.debug(shlex.join(completed_process.args))
    raise SystemExit(completed_process.returncode)


def timeout(minutes) -> None:
    if minutes and float(minutes) > 0:
        seconds = int(float(minutes) * 60)

        def exit_timeout(_signal, _frame):
            print(f"\nReached timeout... ({seconds}s)")
            raise SystemExit(124)

        signal.signal(signal.SIGALRM, exit_timeout)
        signal.alarm(seconds)


def with_timeout(seconds):  # noqa: ANN201
    def decorator(decorated):
        @functools.wraps(decorated)
        def inner(*args, **kwargs):
            pool = multiprocessing.Pool(1)
            async_result = pool.apply_async(decorated, args, kwargs)
            try:
                return async_result.get(seconds)
            finally:
                pool.close()

        return inner

    return decorator


def os_bg_kwargs() -> dict:
    # prevent ctrl-c from affecting subprocesses first

    if hasattr(os, "setpgrp"):
        return {"start_new_session": True}
    else:
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        # DETACHED_PROCESS = 0x00000008
        # os_kwargs = dict(creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        return {}


def cmd(*command, strict=True, cwd=None, quiet=True, ignore_regexps=None, **kwargs) -> subprocess.CompletedProcess:
    def print_std(s, is_success):
        if ignore_regexps is not None:
            s = "\n".join(l for l in s.splitlines() if not any(r.match(l) for r in ignore_regexps))

        s = s.strip()
        if s:
            if quiet and is_success:
                log.debug(s)
            elif consts.PYTEST_RUNNING:
                log.warning(s)
            else:
                log.info(s)
        return s

    try:
        r = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd,
            errors=sys.getfilesystemencodeerrors(),
            **os_bg_kwargs(),
            **kwargs,
        )
    except UnicodeDecodeError:
        print(repr(command))
        raise

    log.debug(r.args)
    print_std(r.stdout, r.returncode == 0)
    print_std(r.stderr, r.returncode == 0)
    if r.returncode != 0:
        if strict:
            raise subprocess.CalledProcessError(r.returncode, shlex.join(command), r.stdout, r.stderr)
        else:
            log.info("[%s] exited %s", shlex.join(command), r.returncode)

    return r


def cmd_detach(*command, **kwargs) -> subprocess.CompletedProcess:
    # https://stackoverflow.com/questions/62521658/python-subprocess-detach-a-process
    # After lb closes, the detached process becomes daemonized (ie. not connected to the terminal so they won't show up in the shell command `jobs`)
    # If you shut down your computer often, you may want to open: `watch progress -wc ffmpeg` in another terminal so that you don't forget many things are in the background
    # If using with ffmpeg remember to include ffmpeg's flag `-nostdin` in the command when calling this function
    stdout = subprocess.DEVNULL
    stderr = subprocess.DEVNULL
    stdin = subprocess.DEVNULL

    command = iterables.conform(command)
    if command[0] in ["fish", "bash"]:
        command = command[0:2] + [shlex.join(command[2:])]
    proc = subprocess.Popen(
        command, stdin=stdin, stdout=stdout, stderr=stderr, close_fds=True, **os_bg_kwargs(), **kwargs
    )
    log.debug("pid %s cmd: %s", proc.pid, command)
    return subprocess.CompletedProcess(command, 0, "Detached command is async")


def cmd_interactive(*command, strict=True) -> subprocess.CompletedProcess:
    return_code = os.spawnvpe(os.P_WAIT, command[0], command, os.environ)

    if return_code != 0:
        msg = f"[{shlex.join(command)}] exited {return_code}"
        if strict:
            raise RuntimeError(msg)
        else:
            log.info(msg)

    return subprocess.CompletedProcess(command, return_code)


def Pclose(process) -> subprocess.CompletedProcess:  # noqa: N802
    try:
        stdout, stderr = process.communicate(input)
    except subprocess.TimeoutExpired as exc:
        log.debug("subprocess.TimeoutExpired")
        process.kill()
        if platform.system() == "Windows":
            exc.stdout, exc.stderr = process.communicate()
        else:
            process.wait()
        raise
    except Exception as e:
        log.debug(e)
        process.kill()
        raise
    return_code = process.poll()
    return subprocess.CompletedProcess(process.args, return_code, stdout, stderr)


class UnplayableFile(RuntimeError):
    pass


class FFProbe:
    def __init__(self, path, *args):
        args = ["ffprobe", "-show_format", "-show_streams", "-show_chapters", "-of", "json", *args, path]
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        out, err = p.communicate()
        if p.returncode != 0:
            log.info("ffprobe %s out %s error %s", p.returncode, out, err)
            if p.returncode == -2:
                raise KeyboardInterrupt
            elif p.returncode == 127:  # Cannot open shared object file
                raise RuntimeError
            elif p.returncode == -6:  # Too many open files
                raise OSError
            else:
                raise UnplayableFile(out, err)
        d = json.loads(out.decode("utf-8"))

        self.path = path

        self.streams = d.get("streams")
        self.chapters = d.get("chapters")
        self.format = d.get("format")

        self.video_streams = []
        self.audio_streams = []
        self.subtitle_streams = []
        self.other_streams = []

        for stream in self.streams:
            if "codec_type" not in stream:
                continue
            elif stream["codec_type"] == "video":
                self.video_streams.append(stream)
            elif stream["codec_type"] == "audio":
                self.audio_streams.append(stream)
            elif stream["codec_type"] == "subtitle":
                self.subtitle_streams.append(stream)
            else:
                self.other_streams.append(stream)

        self.has_video = len(self.video_streams) > 0
        self.has_audio = len(self.audio_streams) > 0

        self.duration = None
        try:
            self.duration = float(self.audio_streams[0]["duration"])
        except Exception:
            pass
        try:
            self.duration = float(self.video_streams[0]["duration"])
        except Exception:
            pass
        try:
            self.duration = float(self.format["duration"])
        except Exception:
            pass
