import argparse, enum, functools, hashlib, logging, math, multiprocessing, os, platform, re, signal, subprocess, sys, textwrap
from ast import literal_eval
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from shutil import which
from typing import Any, Dict, Generator, List, Optional, Union

import humanize
from IPython.core import ultratb
from IPython.terminal.debugger import TerminalPdb
from pychromecast import discovery
from rich.logging import RichHandler

from xklb import consts

try:
    import ipdb
except ModuleNotFoundError:
    pass
else:
    sys.breakpointhook = ipdb.set_trace


def exit_nicely(_signal, _frame):
    print("\nExiting... (Ctrl+C)\n")
    raise SystemExit(130)


signal.signal(signal.SIGINT, exit_nicely)


def no_media_found():
    print("No media found")
    raise SystemExit(2)


def with_timeout(timeout):
    def decorator(decorated):
        @functools.wraps(decorated)
        def inner(*args, **kwargs):
            pool = multiprocessing.Pool(1)
            async_result = pool.apply_async(decorated, args, kwargs)
            try:
                return async_result.get(timeout)
            finally:
                pool.close()

        return inner

    return decorator


def os_bg_kwargs() -> dict:
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


def flatten(xs: Iterable) -> Generator:
    for x in xs:
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        elif isinstance(x, bytes):
            yield x.decode("utf-8")
        else:
            yield x


def conform(list_: Union[str, Iterable]) -> List:
    if not isinstance(list_, list):
        list_ = [list_]
    list_ = flatten(list_)
    list_ = list(filter(bool, list_))
    return list_


def cmd(*command, strict=True, cwd=None, quiet=True, interactive=False, **kwargs) -> subprocess.CompletedProcess:
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

        return "\n".join(conform(filtered_strings))

    def print_std(r_std):
        s = filter_output(r_std)
        if not quiet and s:
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


def trash(f: Union[Path, str]) -> None:
    trash_put = which("trash-put") or which("trash")
    if trash_put is not None:
        cmd(trash_put, f, strict=False)
    else:
        Path(f).unlink(missing_ok=True)


def remove_whitespaace(string) -> str:
    return " ".join(string.split())


def remove_text_inside_brackets(text: str, brackets="()[]") -> str:  # thanks @jfs
    count = [0] * (len(brackets) // 2)  # count open/close brackets
    saved_chars = []
    for character in text:
        for i, b in enumerate(brackets):
            if character == b:  # found bracket
                kind, is_close = divmod(i, 2)
                count[kind] += (-1) ** is_close  # `+1`: open, `-1`: close
                if count[kind] < 0:  # unbalanced bracket
                    count[kind] = 0  # keep it
                else:  # found bracket to remove
                    break
        else:  # character is not a [balanced] bracket
            if not any(count):  # outside brackets
                saved_chars.append(character)
    return "".join(saved_chars)


def get_ip_of_chromecast(device_name):
    cast_infos, browser = discovery.discover_listed_chromecasts(friendly_names=[device_name])
    browser.stop_discovery()
    if not cast_infos:
        print("Target chromecast device not found")
        raise SystemExit(53)

    return cast_infos[0].host


def mpv_enrich(args, media) -> List[dict]:
    for m in media:
        md5 = hashlib.md5(m["path"].encode("utf-8")).hexdigest().upper()
        if Path(args.watch_later_directory, md5).exists():
            m["time_partial_first"] = int(Path(args.watch_later_directory, md5).stat().st_ctime)
            m["time_partial_last"] = int(Path(args.watch_later_directory, md5).stat().st_mtime)
        else:
            m["time_partial_first"] = 0
            m["time_partial_last"] = 0

    return sorted(media, key=lambda m: m.get("time_partial_first") or 0, reverse=True)


def mpv_enrich2(args, media) -> List[dict]:
    md5s = {hashlib.md5(m["path"].encode("utf-8")).hexdigest().upper(): m for m in media}
    paths = list(Path(args.watch_later_directory).glob("*"))
    filtered_list = [
        {
            **(md5s.get(p.stem) or {}),
            "time_partial_first": int(p.stat().st_ctime),
            "time_partial_last": int(p.stat().st_mtime),
        }
        for p in paths
        if md5s.get(p.stem)
    ]

    return sorted(filtered_list, key=lambda m: m.get("time_partial_first") or 0, reverse=False)


def dict_filter_bool(kwargs, keep_0=True) -> Optional[dict]:
    if keep_0:
        filtered_dict = {k: v for k, v in kwargs.items() if v is not None and v != "" and v is not False}
    else:
        filtered_dict = {k: v for k, v in kwargs.items() if v}

    if len(filtered_dict) == 0:
        return None
    return filtered_dict


def list_dict_filter_bool(media: List[dict]) -> List[dict]:
    return [d for d in [dict_filter_bool(d) for d in media] if d]


def cmd_interactive(*command) -> subprocess.CompletedProcess:
    return_code = os.spawnvpe(os.P_WAIT, command[0], command, os.environ)
    return subprocess.CompletedProcess(command, return_code)


def Pclose(process) -> subprocess.CompletedProcess:
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


def chunks(lst, n) -> Generator:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def divisor_gen(n: float) -> Generator:
    large_divisors = []
    for i in range(2, int(math.sqrt(n) + 1)):
        if n % i == 0:
            yield i
            if i * i != n:
                large_divisors.append(n / i)
    for divisor in reversed(large_divisors):
        yield int(divisor)


_RE_COMBINE_WHITESPACE = re.compile(r"\s+")


def combine(*list_) -> Optional[str]:
    list_ = conform(list_)
    if not list_:
        return None

    no_comma = sum([str(s).split(",") for s in list_], [])
    no_semicolon = sum([s.split(";") for s in no_comma], [])
    no_double_space = [_RE_COMBINE_WHITESPACE.sub(" ", s).strip() for s in no_semicolon]
    no_unknown = [x for x in no_double_space if x.lower() not in ("unknown", "none", "und", "")]

    no_duplicates = list(dict.fromkeys(no_unknown))
    return ";".join(no_duplicates)


def safe_unpack(*list_, idx=0) -> Optional[Any]:
    list_ = conform(list_)
    if not list_:
        return None

    try:
        return list_[idx]
    except IndexError:
        return None


def col_resize(tbl: List[Dict], col: str, size=10) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = textwrap.fill(tbl[idx][col], max(10, int(size * (consts.TERMINAL_SIZE.columns / 80))))

    return tbl


def col_naturaldate(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = humanize.naturaldate(datetime.fromtimestamp(int(tbl[idx][col]), tz=timezone.utc))

    return tbl


def col_naturalsize(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            if tbl[idx][col] == 0:
                tbl[idx][col] = None
            else:
                tbl[idx][col] = humanize.naturalsize(tbl[idx][col])

    return tbl


def human_time(seconds) -> Optional[str]:
    if seconds is None or math.isnan(seconds) or seconds == 0:
        return None
    hours = humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="hours", format="%0.0f")
    if len(hours.split(",")) >= 3:
        return hours
    minutes = humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="minutes", format="%0.0f")
    if len(minutes.split(",")) >= 2:
        return minutes

    return humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="minutes")


def col_duration(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = human_time(tbl[idx][col])

    col_resize(tbl, "duration", 6)
    return tbl


class argparse_dict(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        try:
            d = {}
            k_eq_v = list(flatten([val.split(" ") for val in values]))
            for s in k_eq_v:
                k, v = s.split("=")
                if any([sym in v for sym in ("[", "{")]):
                    d[k] = literal_eval(v)
                else:
                    d[k] = v

        except ValueError as ex:
            raise argparse.ArgumentError(self, f'Could not parse argument "{values}" as k1=1 k2=2 format {ex}')
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


def filter_namespace(args, config_opts):
    return dict_filter_bool({k: v for k, v in args.__dict__.items() if k in config_opts})
