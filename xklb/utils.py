import argparse, enum, functools, hashlib, logging, math, multiprocessing, os, platform, random, re, shlex, shutil, signal, string, subprocess, sys, tempfile, textwrap, time
from ast import literal_eval
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from random import shuffle
from shutil import which
from typing import Any, Dict, Generator, List, NoReturn, Optional, Union

import humanize
from IPython.core import ultratb
from IPython.terminal.debugger import TerminalPdb
from rich import prompt
from rich.logging import RichHandler

from xklb import consts

try:
    import ipdb
except ModuleNotFoundError:
    pass
else:
    sys.breakpointhook = ipdb.set_trace


def run_once(f):  # noqa: ANN201
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not f.has_run:
            result = f(*args, **kwargs)
            f.has_run = True
            return result
        return None

    f.has_run = False
    return wrapper


@run_once
def argparse_log() -> logging.Logger:
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
    except Exception as e:
        log.debug(e)

    log_levels = [logging.WARNING, logging.INFO, logging.DEBUG]
    logging.root.handlers = []  # clear any existing handlers
    logging.basicConfig(
        level=log_levels[min(len(log_levels) - 1, args.verbose)],
        format="%(message)s",
        handlers=[RichHandler(show_time=False, show_level=False, show_path=False)],
    )
    return logging.getLogger()


log = argparse_log()


def exit_nicely(_signal, _frame) -> NoReturn:
    log.warning("\nExiting... (Ctrl+C)")
    raise SystemExit(130)


signal.signal(signal.SIGINT, exit_nicely)


def repeat_until_same(fn):  # noqa: ANN201
    def wrapper(*args, **kwargs):
        p = args[0]
        while True:
            p1 = p
            p = fn(p, *args[1:], **kwargs)
            # print(fn.__name__, p)
            if p1 == p:
                break
        return p

    return wrapper


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


def os_bg_kwargs() -> Dict:
    # prevent ctrl-c from affecting subprocesses first

    if hasattr(os, "setpgrp"):
        return {"start_new_session": True}
    else:
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        # DETACHED_PROCESS = 0x00000008
        # os_kwargs = dict(creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        return {}


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


def cmd(*command, strict=True, cwd=None, quiet=True, **kwargs) -> subprocess.CompletedProcess:
    EXP_FILTER = re.compile(
        "|".join(
            [
                r".*Stream #0:0.*Audio: opus, 48000 Hz, .*, fltp",
                r".*encoder.*",
                r".*Metadata:",
                r".*TSRC.*",
            ],
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
    r.stdout = print_std(r.stdout)
    r.stderr = print_std(r.stderr)
    if r.returncode != 0:
        log.info("[%s]: ERROR %s", shlex.join(command), r.returncode)
        if strict:
            msg = f"[{command}] exited {r.returncode}"
            raise RuntimeError(msg)

    return r


def timeout(minutes) -> None:
    if minutes and float(minutes) > 0:
        seconds = int(float(minutes) * 60)

        def exit_timeout(_signal, _frame):
            print(f"\nReached timeout... ({seconds}s)")
            cmd("pkill", "mpv")
            raise SystemExit(124)

        signal.signal(signal.SIGALRM, exit_timeout)
        signal.alarm(seconds)


def no_media_found() -> NoReturn:
    log.error("No media found")
    raise SystemExit(2)


def sanitize_url(args, path: str) -> str:
    matches = consts.REGEX_SUBREDDIT.match(path)
    if matches:
        subreddit = conform(matches.groups())[0]
        frequency = consts.Frequency.Monthly
        if hasattr(args, "frequency"):
            frequency = args.frequency
        return "https://old.reddit.com/r/" + subreddit + "/top/?sort=top&t=" + consts.reddit_frequency(frequency)

    if "/m." in path:
        return path.replace("/m.", "/www.")

    return path


def cmd_detach(*command, **kwargs) -> subprocess.CompletedProcess:
    # https://stackoverflow.com/questions/62521658/python-subprocess-detach-a-process
    # After lb closes, the detached process becomes daemonized (ie. not connected to the terminal so they won't show up in the shell command `jobs`)
    # If you shut down your computer often, you may want to open: `watch progress -wc ffmpeg` in another terminal so that you don't forget many things are in the background
    # If using with ffmpeg remember to include ffmpeg's flag `-nostdin` in the command when calling this function
    stdout = os.open(os.devnull, os.O_WRONLY)
    stderr = os.open(os.devnull, os.O_WRONLY)
    stdin = os.open(os.devnull, os.O_RDONLY)

    command = conform(command)
    if command[0] in ["fish", "bash"]:
        command = command[0:2] + [shlex.join(command[2:])]
    subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, close_fds=True, **os_bg_kwargs(), **kwargs)
    return subprocess.CompletedProcess(command, 0, "Detached command is async")


def cmd_interactive(*command) -> subprocess.CompletedProcess:
    return_code = os.spawnvpe(os.P_WAIT, command[0], command, os.environ)
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


def file_temp_copy(src) -> str:
    fo_dest = tempfile.NamedTemporaryFile(delete=False)
    with open(src, "r+b") as fo_src:
        shutil.copyfileobj(fo_src, fo_dest)
    fo_dest.seek(0)
    fname = fo_dest.name
    fo_dest.close()
    return fname


def trash(f: Union[Path, str], detach=True) -> None:
    trash_put = which("trash-put") or which("trash")
    if trash_put is not None:
        if not detach:
            cmd(trash_put, f, strict=False)
            return
        try:
            cmd_detach(trash_put, f)
        except Exception:
            cmd(trash_put, f, strict=False)
    else:
        Path(f).unlink(missing_ok=True)


def remove_consecutive_whitespace(s) -> str:
    return " ".join(s.split())  # spaces, tabs, and newlines


def remove_consecutive(s, char=" ") -> str:
    return re.sub("\\" + char + "+", char, s)


@repeat_until_same
def remove_consecutives(s, chars) -> str:
    for char in chars:
        s = remove_consecutive(s, char)
    return s


@repeat_until_same
def remove_prefixes(s, prefixes) -> str:
    for prefix in prefixes:
        if s.startswith(prefix):
            s = s.replace(prefix, "", 1)
    return s


@repeat_until_same
def remove_suffixes(s, suffixes) -> str:
    for suffix in suffixes:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


@repeat_until_same
def clean_string(p) -> str:
    p = (
        p.replace("*", "")
        .replace("&", "")
        .replace("%", "")
        .replace("$", "")
        .replace("#", "")
        .replace(" @", "")
        .replace("?.", ".")
        .replace("!.", ".")
        .replace("^", "")
        .replace("'", "")
        .replace('"', "")
        .replace(")", "")
    )
    p = remove_consecutives(p, chars=["."])
    p = (
        p.replace("(", " ")
        .replace("-.", ".")
        .replace(" :", ":")
        .replace(" - ", " ")
        .replace("- ", " ")
        .replace(" -", " ")
        .replace(" _ ", "_")
        .replace(" _", "_")
        .replace("_ ", "_")
    )
    p = remove_consecutive_whitespace(p)
    return p


def clean_path(b, dot_space=False) -> str:
    import ftfy

    p = b.decode("utf-8", "backslashreplace")
    p = ftfy.fix_text(p, explain=False)
    path = Path(p)
    ext = path.suffix

    parent = [clean_string(part) for part in path.parent.parts]
    stem = clean_string(path.stem)
    log.debug("cleaned %s %s", parent, stem)

    parent = [remove_prefixes(part, [" ", "-"]) for part in parent]
    log.debug("parent_prefixes %s %s", parent, stem)
    parent = [remove_suffixes(part, [" ", "-", "_", "."]) for part in parent]
    log.debug("parent_suffixes %s %s", parent, stem)

    stem = remove_prefixes(stem, [" ", "-"])
    stem = remove_suffixes(stem, [" ", "-", "."])
    log.debug("stem %s %s", parent, stem)

    parent = ["_" if part == "" else part for part in parent]
    p = str(Path(*parent) / stem[:1024])

    if dot_space:
        p = p.replace(" ", ".")

    return p + ext


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


def get_ip_of_chromecast(device_name) -> str:
    from pychromecast import discovery

    cast_infos, browser = discovery.discover_listed_chromecasts(friendly_names=[device_name])
    browser.stop_discovery()
    if not cast_infos:
        log.error("Target chromecast device not found")
        raise SystemExit(53)

    return cast_infos[0].host


def path_to_mpv_watchlater_md5(path: str) -> str:
    return hashlib.md5(path.encode("utf-8")).hexdigest().upper()


def mpv_enrich(args, media) -> List[Dict]:
    for m in media:
        md5 = path_to_mpv_watchlater_md5(m["path"])
        metadata_path = Path(args.watch_later_directory, md5)
        if metadata_path.exists():
            m["time_partial_first"] = int(metadata_path.stat().st_ctime)
            m["time_partial_last"] = int(metadata_path.stat().st_mtime)
        else:
            m["time_partial_first"] = 0
            m["time_partial_last"] = 0

    return sorted(media, key=lambda m: m.get("time_partial_first") or 0, reverse=True)


def mpv_watchlater_value(path, key) -> Optional[str]:
    data = Path(path).read_text().splitlines()
    for s in data:
        if s.startswith(key + "="):
            return s.split("=")[1]
    return None


def filter_episodic(args, media: List[Dict]) -> List[Dict]:
    parent_dict = {}
    for m in media:
        path = Path(m["path"])
        parent_path = path.parent
        parent_dict.setdefault(parent_path, 0)
        parent_dict[parent_path] += 1

    filtered_media = []
    for m in media:
        path = Path(m["path"])
        parent_path = path.parent

        siblings = parent_dict[parent_path]

        if args.lower is not None and siblings < args.lower:
            continue
        elif args.upper is not None and siblings > args.upper:
            continue
        else:
            filtered_media.append(m)

    return filtered_media


def safe_int(s) -> Optional[int]:
    try:
        return int(float(s))
    except Exception:
        return None


def mpv_enrich2(args, media) -> List[Dict]:
    md5s = {path_to_mpv_watchlater_md5(m["path"]): m for m in media}
    paths = set(Path(args.watch_later_directory).glob("*"))

    previously_watched = [
        {
            **(md5s.get(p.stem) or {}),
            "time_partial_first": int(p.stat().st_ctime),
            "time_partial_last": int(p.stat().st_mtime),
            "progress": safe_int(mpv_watchlater_value(p, "start")),
        }
        for p in paths
        if md5s.get(p.stem)
    ]
    if "s" in args.partial:  # only unseen
        previously_watched_paths = [m["path"] for m in previously_watched]
        return [m for m in media if m["path"] not in previously_watched_paths]

    def mpv_progress(m):
        progress = m.get("progress")
        duration = m.get("duration")
        if not progress:
            return 0.0
        if not duration:
            return progress / 100  # TODO: idk

        if "w" in args.partial:  # weight by total time
            return progress / duration * progress
        else:
            return progress / duration

    def sorting_hat():
        if "f" in args.partial:  # first-viewed
            return lambda m: m.get("time_partial_first") or 0
        elif "p" in args.partial:  # sort by remaining duration
            return mpv_progress

        return lambda m: m.get("time_partial_last") or m.get("time_partial_first") or 0

    reverse_chronology = True
    if "o" in args.partial:  # oldest first
        reverse_chronology = False

    key = sorting_hat()
    if args.print:
        reverse_chronology = not reverse_chronology

    media = sorted(
        previously_watched,
        key=key,
        reverse=reverse_chronology,
    )

    if args.skip:
        media = media[int(args.skip) :]

    return media


def dict_filter_bool(kwargs, keep_0=True) -> Optional[dict]:
    if kwargs is None:
        return None

    if keep_0:
        filtered_dict = {k: v for k, v in kwargs.items() if v is not None and v != "" and v is not False}
    else:
        filtered_dict = {k: v for k, v in kwargs.items() if v}

    if len(filtered_dict) == 0:
        return None
    return filtered_dict


def list_dict_filter_bool(media: List[dict], keep_0=True) -> List[dict]:
    return [d for d in [dict_filter_bool(d, keep_0) for d in media] if d]


def dict_filter_keys(kwargs, keys) -> Optional[dict]:
    filtered_dict = {k: v for k, v in kwargs.items() if k not in keys}
    if len(filtered_dict) == 0:
        return None
    return filtered_dict


def list_dict_filter_keys(media: List[dict], keys) -> List[dict]:
    return [d for d in [dict_filter_keys(d, keys) for d in media] if d]


def list_dict_filter_unique(data: List[dict]) -> List[dict]:
    if len(data) == 0:
        return []

    unique_values = {}
    for key in set.intersection(*(set(d.keys()) for d in data)):
        values = {d[key] for d in data if key in d}
        if len(values) > 1:
            unique_values[key] = values
    filtered_data = [{k: v for k, v in d.items() if k in unique_values} for d in data]
    return filtered_data


def chunks(lst, n) -> Generator:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def divisor_gen(n: int) -> Generator:
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

    no_comma = sum((str(s).split(",") for s in list_), [])
    no_semicolon = sum((s.split(";") for s in no_comma), [])
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
            tbl[idx][col] = humanize.naturaldate(datetime.fromtimestamp(int(tbl[idx][col]), timezone.utc))

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

    PRECISION_YEARS = 3
    hours = humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="hours", format="%0.0f")
    if len(hours.split(",")) >= PRECISION_YEARS:
        return hours

    PRECISION_MONTHS = 2
    minutes = humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="minutes", format="%0.0f")
    if len(minutes.split(",")) >= PRECISION_MONTHS:
        return minutes

    return humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="minutes")


def col_duration(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = human_time(tbl[idx][col])

    col_resize(tbl, "duration", 6)
    return tbl


class ArgparseDict(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        try:
            d = {}
            k_eq_v = list(flatten([val.split(" ") for val in values]))
            for s in k_eq_v:
                k, v = s.split("=")
                if any(sym in v for sym in ("[", "{")):
                    d[k] = literal_eval(v)
                else:
                    d[k] = v

        except ValueError as ex:
            msg = f'Could not parse argument "{values}" as k1=1 k2=2 format {ex}'
            raise argparse.ArgumentError(self, msg) from ex
        setattr(args, self.dest, d)


class ArgparseEnum(argparse.Action):
    def __init__(self, **kwargs) -> None:
        # Pop off the type value
        enum_type = kwargs.pop("type", None)

        # Ensure an Enum subclass is provided
        if enum_type is None:
            raise ValueError("type must be assigned an Enum when using EnumAction")
        if not issubclass(enum_type, enum.Enum):
            raise TypeError("type must be an Enum when using EnumAction")

        # Generate choices from the Enum
        kwargs.setdefault("choices", tuple(e.value for e in enum_type))

        super().__init__(**kwargs)

        self._enum = enum_type

    def __call__(self, parser, namespace, values, option_string=None):
        # Convert value back into an Enum
        value = self._enum(values)
        setattr(namespace, self.dest, value)


def filter_namespace(args, config_opts) -> Optional[Dict]:
    return dict_filter_bool({k: v for k, v in args.__dict__.items() if k in config_opts})


def ensure_playlists_exists(args) -> None:
    if "playlists" not in args.db.table_names():
        with args.db.conn:
            args.db.conn.execute("create table playlists (path text, category text, ie_key text, time_deleted int)")


def clear_input() -> None:
    if platform.system() == "Linux":
        from termios import TCIFLUSH, tcflush

        tcflush(sys.stdin, TCIFLUSH)
    elif platform.system() == "Windows":
        if getattr(clear_input, "kbhit", None) is None:
            from msvcrt import getch, kbhit  # type: ignore

            clear_input.kbhit = kbhit
            clear_input.getch = getch

        # Try to flush the buffer
        while clear_input.kbhit():
            clear_input.getch()


def set_readline_completion(list_) -> None:
    try:
        import readline
    except ModuleNotFoundError:
        # "Windows not supported"
        return

    def create_completer(list_):
        def list_completer(_text, state):
            line = readline.get_line_buffer()

            if not line:
                min_depth = min([s.count(os.sep) for s in list_]) + 1
                result_list = [c + " " for c in list_ if c.count(os.sep) <= min_depth]
                shuffle(result_list)
                return result_list[:25][state]
            else:
                match_list = [s for s in list_ if s.startswith(line)]
                min_depth = min([s.count(os.sep) for s in match_list]) + 1
                result_list = [c + " " for c in match_list if c.count(os.sep) <= min_depth]
                shuffle(result_list)
                return result_list[:15][state]

        return list_completer

    readline.set_completer(create_completer(list_))
    readline.set_completer_delims("\t")
    readline.parse_and_bind("tab: complete")
    return


def filter_file(path, sieve) -> None:
    with open(path) as fr:
        lines = fr.readlines()
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp:
            temp.writelines(line for line in lines if line.rstrip() not in sieve)
            temp.flush()
            os.fsync(temp.fileno())
    shutil.copy(temp.name, path)
    Path(temp.name).unlink()


def get_mount_stats(src_mounts) -> List[Dict[str, Union[str, int]]]:
    mount_space = []
    total_used = 1
    total_free = 1
    grand_total = 1
    for src_mount in src_mounts:
        total, used, free = shutil.disk_usage(src_mount)
        total_used += used
        total_free += free
        grand_total += total
        mount_space.append((src_mount, used, free, total))

    return [
        {"mount": mount, "used": used / total_used, "free": free / total_free, "total": total / grand_total}
        for mount, used, free, total in mount_space
    ]


def print_mount_stats(space) -> None:
    print("Relative disk utilization:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['used'] * 80)} {d['used']:.1%}")

    print("\nRelative free space:")
    for d in space:
        print(f"{d['mount']}: {'#' * int(d['free'] * 80)} {d['free']:.1%}")


def mount_stats() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("mounts", nargs="+")
    args = parser.parse_args()
    print_mount_stats(get_mount_stats(args.mounts))


def human_to_bytes(input_str) -> int:
    byte_map = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4, "pb": 1024**5}

    input_str = input_str.strip().lower()

    value = re.findall(r"\d+\.?\d*", input_str)[0]
    unit = re.findall(r"[a-z]+", input_str, re.IGNORECASE)

    if unit:
        unit = unit[0]
        unit = "".join(unit.split("i"))

        if not unit.endswith("b"):  # handle cases like 'k'
            unit += "b"
    else:
        unit = "mb"

    unit_multiplier = byte_map.get(unit, 1024**2)  # default to MB
    return int(float(value) * unit_multiplier)


def parse_human_to_sql(human_to_x, var, sizes) -> str:
    size_rules = ""

    for size in sizes:
        if ">" in size:
            size_rules += f"and {var} > {human_to_x(size.lstrip('>'))} "
        elif "<" in size:
            size_rules += f"and {var} < {human_to_x(size.lstrip('<'))} "
        elif "+" in size:
            size_rules += f"and {var} >= {human_to_x(size.lstrip('+'))} "
        elif "-" in size:
            size_rules += f"and {human_to_x(size.lstrip('-'))} >= {var} "
        else:
            # approximate size rule +-10%
            size_bytes = human_to_x(size)
            size_rules += (
                f"and {int(size_bytes + (size_bytes /10))} >= {var} and {var} >= {int(size_bytes - (size_bytes /10))} "
            )
    return size_rules


def human_to_seconds(input_str) -> int:
    time_units = {
        "s": 1,
        "sec": 1,
        "second": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "h": 3600,
        "hr": 3600,
        "hour": 3600,
        "d": 86400,
        "day": 86400,
        "w": 604800,
        "week": 604800,
        "mo": 2592000,
        "mon": 2592000,
        "month": 2592000,
        "y": 31536000,
        "yr": 31536000,
        "year": 31536000,
    }

    input_str = input_str.strip().lower()

    value = re.findall(r"\d+\.?\d*", input_str)[0]
    unit = re.findall(r"[a-z]+", input_str, re.IGNORECASE)

    if unit:
        unit = unit[0]
        if unit != "s":
            unit = unit.rstrip("s")
    else:
        unit = "m"

    return int(float(value) * time_units[unit])


def pipe_print(x) -> None:
    try:
        print(x, flush=True)
    except BrokenPipeError:
        sys.stdout = None
        sys.exit(141)


def random_string() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=5))


def random_filename(path) -> str:
    ext = Path(path).suffix
    path = str(Path(path).with_suffix(""))
    return f"{path}.{random_string()}{ext}"


def confirm(*args, **kwargs) -> bool:
    clear_input()
    return prompt.Confirm.ask(*args, **kwargs, default=False)


def connect_mpv(ipc_socket, start_mpv=False):  # noqa: ANN201
    try:
        from python_mpv_jsonipc import MPV

        return MPV(start_mpv, ipc_socket)
    except (ConnectionRefusedError, FileNotFoundError):
        Path(ipc_socket).unlink(missing_ok=True)

    return None


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
        mpv_playhead = safe_int(mpv_watchlater_value(metadata_path, "start"))
    except Exception:
        mpv_playhead = None

    for playhead in sorted([mpv_playhead or 0, python_playhead], reverse=True):
        if playhead > 0 and (media_duration is None or media_duration >= playhead):
            return playhead
    return None
