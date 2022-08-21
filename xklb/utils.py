import argparse
import enum
import logging
import os
import platform
import re
import signal
import subprocess
import sys
import textwrap
from collections.abc import Iterable
from datetime import timedelta
from functools import wraps
from pathlib import Path
from tempfile import gettempdir
from types import SimpleNamespace
from typing import Union

import humanize
import numpy as np
import pandas as pd
import psutil
from IPython.core import ultratb
from IPython.terminal.debugger import TerminalPdb
from pychromecast import discovery
from rich.logging import RichHandler

try:
    import ipdb
except ImportError:
    pass
else:
    sys.breakpointhook = ipdb.set_trace

SQLITE_PARAM_LIMIT = 32765
FAKE_SUBTITLE = os.path.join(gettempdir(), "sub.srt")  # https://github.com/skorokithakis/catt/issues/393
CAST_NOW_PLAYING = os.path.join(gettempdir(), "catt_playing")
DEFAULT_MPV_SOCKET = os.path.join(gettempdir(), "mpv_socket")
DEFAULT_PLAY_QUEUE = 120

pd.set_option("display.float_format", lambda x: "%.5f" % x)


def signal_handler(signal, frame):
    print("\nExiting... (Ctrl+C)\n")
    sys.exit(130)


signal.signal(signal.SIGINT, signal_handler)


class SC:
    watch = "watch"
    listen = "listen"
    filesystem = "filesystem"
    tubewatch = "tubewatch"
    tubelisten = "tubelisten"
    tabs = "tabs"


def get_ip_of_chromecast(device_name):
    cast_infos, browser = discovery.discover_listed_chromecasts(friendly_names=[device_name])
    browser.stop_discovery()
    if len(cast_infos) == 0:
        print("Target chromecast device not found")
        exit(53)

    return cast_infos[0].host


def os_bg_kwargs():
    if hasattr(os, "setpgrp"):
        os_kwargs = dict(start_new_session=True)
    else:
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        DETACHED_PROCESS = 0x00000008
        os_kwargs = dict(creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    return os_kwargs


def run_once(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not f.has_run:
            result = f(*args, **kwargs)
            f.has_run = True
            return result

    f.has_run = False
    return wrapper


@run_once
def argparse_log():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args, _unknown = parser.parse_known_args()
    # print(args)

    try:
        if args.verbose > 0 and os.getpgrp() == os.tcgetpgrp(sys.stdout.fileno()):
            sys.excepthook = ultratb.FormattedTB(
                mode="Context",
                color_scheme="Neutral",
                call_pdb=True,
                debugger_cls=TerminalPdb,
            )
        else:
            pass
    except Exception:
        pass

    log_levels = [logging.WARNING, logging.INFO, logging.DEBUG]
    logging.root.handlers = []  # clear any existing handlers
    logging.basicConfig(
        level=log_levels[min(len(log_levels) - 1, args.verbose)],
        format="%(message)s",
        handlers=[RichHandler(show_time=False, show_level=False, show_path=False)],
    )
    return logging.getLogger()


log = argparse_log()


def cmd(*command, strict=True, cwd=None, quiet=True, interactive=False, **kwargs):
    EXP_FILTER = re.compile(
        "|".join(
            [
                r".*Stream #0:0.*Audio: opus, 48000 Hz, .*, fltp",
                r".*encoder.*",
                r".*Metadata:",
                r".*TSRC.*",
            ]
        ),
        re.IGNORECASE,
    )

    def filter_output(string):
        filtered_strings = []
        for s in string.strip().splitlines():
            if not EXP_FILTER.match(s):
                filtered_strings.append(s)

        return "\n".join(list(filter(None, filtered_strings)))

    def print_std(r_std):
        s = filter_output(r_std)
        if not quiet and len(s) > 0:
            print(s)
        return s

    if len(command) == 1 and kwargs.get("shell") is True:
        command = command[0]

    os_kwargs = {} if interactive else os_bg_kwargs()
    r = subprocess.run(command, capture_output=True, text=True, cwd=cwd, **os_kwargs, **kwargs)

    log.debug(r.args)
    r.stdout = print_std(r.stdout)
    r.stderr = print_std(r.stderr)
    if r.returncode != 0:
        log.info(f"ERROR {r.returncode}")
        if strict:
            raise Exception(f"[{command}] exited {r.returncode}")

    return r


def cmd_interactive(*cmd, **kwargs):
    return_code = os.spawnvpe(os.P_WAIT, cmd[0], cmd, os.environ)
    return subprocess.CompletedProcess(cmd, return_code)


def Pclose(process):
    try:
        stdout, stderr = process.communicate(input)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        if platform.system() == "Windows":
            exc.stdout, exc.stderr = process.communicate()
        else:
            process.wait()
        raise
    except Exception:
        process.kill()
        raise
    return_code = process.poll()
    return subprocess.CompletedProcess(process.args, return_code, stdout, stderr)


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def flatten(xs: Iterable):
    for x in xs:
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        elif isinstance(x, bytes):
            yield x.decode("utf-8")
        else:
            yield x


def conform(list_: Union[str, Iterable]):
    if not isinstance(list_, list):
        list_ = [list_]
    list_ = flatten(list_)
    list_ = list(filter(None, list_))
    return list_


def get_media_files(path, audio=False):
    FFMPEG_DEMUXERS = (
        "str|aa|aax|acm|adf|adp|dtk|ads|ss2|adx|aea|afc|aix|al|apl"
        "|mac|aptx|aptxhd|aqt|ast|obu|avi|avr|avs|avs2|avs3|bfstm|bcstm|binka"
        "|bit|bmv|brstm|cdg|cdxl|xl|c2|302|daud|str|adp|dav|dss|dts|dtshd|dv"
        "|dif|cdata|eac3|paf|fap|flm|flv|fsb|fwse|g722|722|tco|rco"
        "|g723_1|g729|genh|gsm|h261|h26l|h264|264|avc|hca|hevc|h265|265|idf"
        "|ifv|cgi|ipu|sf|ircam|ivr|kux|669|abc|amf|ams|dbm|dmf|dsm|far|it|mdl"
        "|med|mid|mod|mt2|mtm|okt|psm|ptm|s3m|stm|ult|umx|xm|itgz|itr|itz"
        "|mdgz|mdr|mdz|s3gz|s3r|s3z|xmgz|xmr|xmz|669|amf|ams|dbm|digi|dmf"
        "|dsm|dtm|far|gdm|ice|imf|it|j2b|m15|mdl|med|mmcmp|mms|mo3|mod|mptm"
        "|mt2|mtm|nst|okt|plm|ppm|psm|pt36|ptm|s3m|sfx|sfx2|st26|stk|stm"
        "|stp|ult|umx|wow|xm|xpk|flv|dat|lvf|m4v|mkv|mk3d|mka|mks|webm|mca|mcc"
        "|mjpg|mjpeg|mpo|j2k|mlp|mods|moflex|mov|mp4|3gp|3g2|mj2|psp|m4b"
        "|ism|ismv|isma|f4v|mp2|mpa|mpc|mjpg|mpl2|msf|mtaf|ul|musx|mvi|mxg"
        "|v|nist|sph|nsp|nut|obu|oma|omg|pjs|pvf|yuv|cif|qcif|rgb|rt|rsd"
        "|rsd|rso|sw|sb|sami|sbc|msbc|sbg|scc|sdr2|sds|sdx|ser|sga|shn|vb|son|imx"
        "|sln|mjpg|stl|sup|svag|svs|tak|thd|tta|ans|art|asc|diz|ice|vt|ty|ty+|uw|ub"
        "|v210|yuv10|vag|vc1|rcv|viv|vpk|vqf|vql|vqe|wsd|xmv|xvag|yop|y4m"
    )
    if audio:
        audio_only = "|opus|oga|ogg|mp3|m2a|m4a|flac|wav|wma|aac|aa3|ac3|ape"
        FFMPEG_DEMUXERS += audio_only

    FFMPEG_ENDINGS = FFMPEG_DEMUXERS.split("|")
    video_files = []
    for f in Path(path).resolve().rglob("*"):
        if f.is_file() and (f.suffix.lower()[1:] in FFMPEG_ENDINGS):
            video_files.append(str(f))

    return video_files


def compile_query(query, *args):
    if len(args) == 1 and (not args[0]):
        number_of_arguments = 0

    number_of_question_marks = query.count("?")
    number_of_arguments = len(args)
    if number_of_arguments != number_of_question_marks:
        raise Exception(
            f"Number of bindings mismatched. The query uses {number_of_question_marks}, but {number_of_arguments} parameters bound."
        )

    for a in args:
        query = query.replace("?", "'" + str(a) + "'", 1)

    return query


def print_query(query, bindings):
    return re.sub(r"\n\s+", r"\n", compile_query(query, *bindings))


def single_column_tolist(array_to_unpack, column_name: Union[str, int] = 1):
    return list(
        map(
            lambda x: x[column_name],
            array_to_unpack,
        )
    )


def filter_None(kwargs):
    return {k: v for k, v in kwargs.items() if v}


_RE_COMBINE_WHITESPACE = re.compile(r"\s+")


def combine(*list_):
    list_ = conform(list_)
    if len(list_) == 0:
        return None

    no_comma = sum([s.split(",") for s in list_], [])
    no_semicolon = sum([s.split(";") for s in no_comma], [])
    no_double_space = [_RE_COMBINE_WHITESPACE.sub(" ", s).strip() for s in no_semicolon]
    no_unknown = [x for x in no_double_space if x.lower() not in ["unknown", "none", "und", ""]]

    no_duplicates = list(set(no_unknown))
    return ";".join(no_duplicates)


def safe_unpack(*list_, idx=0):
    list_ = conform(list_)
    if len(list_) == 0:
        return None

    try:
        return list_[idx]
    except IndexError:
        return None


try:
    TERMINAL_SIZE = os.get_terminal_size()
except Exception:
    TERMINAL_SIZE = SimpleNamespace(columns=80, lines=60)


def resize_col(tbl, col, size=10):
    if col in tbl.columns:
        tbl[[col]] = tbl[[col]].applymap(
            lambda x: None if x is None else textwrap.fill(x, max(10, int(size * (TERMINAL_SIZE.columns / 80))))
        )
    return tbl


def human_time(seconds):
    if seconds is None or np.isnan(seconds):
        return None
    hours = humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="hours", format="%0.0f")
    if len(hours.split(",")) > 2:
        return hours
    minutes = humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="minutes", format="%0.0f")
    if len(minutes.split(",")) > 1:
        return minutes
    else:
        return humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="minutes")


def pkill(*command, strict=True):
    found = 0
    for process in psutil.process_iter():
        if process.cmdline() == command:
            process.terminate()
            found = 1
            break
    if strict and found == 0:
        raise Exception("Process not found")


class argparse_dict(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        try:
            d = dict(map(lambda x: x.split("="), flatten([v.split(" ") for v in values])))
        except ValueError as ex:
            raise argparse.ArgumentError(self, f'Could not parse argument "{values}" as k1=1 k2=2 format')
        setattr(args, self.dest, d)


class argparse_enum(argparse.Action):
    def __init__(self, **kwargs):
        # Pop off the type value
        enum_type = kwargs.pop("type", None)

        # Ensure an Enum subclass is provided
        if enum_type is None:
            raise ValueError("type must be assigned an Enum when using EnumAction")
        if not issubclass(enum_type, enum.Enum):
            raise TypeError("type must be an Enum when using EnumAction")

        # Generate choices from the Enum
        kwargs.setdefault("choices", tuple(e.value for e in enum_type))

        super(argparse_enum, self).__init__(**kwargs)

        self._enum = enum_type

    def __call__(self, parser, namespace, values, option_string=None):
        # Convert value back into an Enum
        value = self._enum(values)
        setattr(namespace, self.dest, value)
