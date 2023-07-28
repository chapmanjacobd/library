import argparse, csv, functools, hashlib, logging, math, multiprocessing, os, platform, random, re, shlex, shutil, signal, string, subprocess, sys, tempfile, time
from ast import literal_eval
from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from shutil import which
from timeit import default_timer
from typing import Any, Dict, Iterator, List, NoReturn, Optional, Union

import humanize
from IPython.core import ultratb
from IPython.terminal import debugger
from rich import prompt
from rich.logging import RichHandler

from xklb import consts
from xklb.scripts.mining import data

sys.breakpointhook = debugger.set_trace


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
                mode="Verbose" if args.verbose > 1 else "Context",
                color_scheme="Neutral",
                call_pdb=True,
                debugger_cls=debugger.TerminalPdb,
            )
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


def flatten(xs: Iterable) -> Iterator:
    for x in xs:
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        elif isinstance(x, bytes):
            yield x.decode("utf-8")
        else:
            yield x


def flatten_dict(nested_dict, parent_key="", sep="_", passthrough_keys=None):
    if passthrough_keys is None:
        passthrough_keys = []
    flattened_dict = {}
    for key, value in nested_dict.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict) and key not in passthrough_keys:
            flattened_dict.update(flatten_dict(value, new_key, sep, passthrough_keys))
        else:
            flattened_dict[new_key] = value
    return flattened_dict


def conform(list_: Union[str, Iterable]) -> List:
    if not list_:
        return []
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
        frequency = "monthly"
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


def trash(path: Union[Path, str], detach=True) -> None:
    if Path(path).exists():
        trash_put = which("trash-put") or which("trash")
        if trash_put is not None:
            if not detach:
                cmd(trash_put, path, strict=False)
                return
            try:
                cmd_detach(trash_put, path)
            except Exception:
                cmd(trash_put, path, strict=False)
        else:
            Path(path).unlink(missing_ok=True)


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


def path_to_sentence(s):
    return remove_consecutive_whitespace(
        s.replace("/", " ")
        .replace("\\", " ")
        .replace(".", " ")
        .replace("[", " ")
        .replace("(", " ")
        .replace("]", " ")
        .replace(")", " ")
        .replace("{", " ")
        .replace("}", " ")
        .replace("_", " ")
        .replace("-", " "),
    )


def safe_int(s) -> Optional[int]:
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def concat(*args):
    return (part for part in args if part)


def lower_keys(input_dict):
    output_dict = {}
    for key, value in input_dict.items():
        lowercase_key = key.lower()
        if lowercase_key in output_dict:
            log.warning("Overriding key %s: %s -> %s", lowercase_key, output_dict[lowercase_key], value)
        output_dict[lowercase_key] = value
    return output_dict


def extract_words(string):
    if not string:
        return None

    cleaned_string = re.sub(r"[^\w\s]", " ", string)
    words = [remove_consecutive_whitespace(s) for s in cleaned_string.split()]
    words = [
        s
        for s in words
        if not (s.lower() in data.stop_words or s.lower() in data.prepositions or safe_int(s) is not None)
    ]
    return words


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


def mpv_watchlater_value(path, key) -> Optional[str]:
    data = Path(path).read_text().splitlines()
    for s in data:
        if s.startswith(key + "="):
            return s.split("=")[1]
    return None


def history_sort(args, media) -> List[Dict]:
    if "s" in args.partial:  # skip; only play unseen
        previously_watched_paths = [m["path"] for m in media if m["time_first_played"]]
        return [m for m in media if m["path"] not in previously_watched_paths]

    def mpv_progress(m):
        playhead = m.get("playhead")
        duration = m.get("duration")
        if not playhead:
            return float("-inf")
        if not duration:
            return float("-inf")

        if "p" in args.partial and "t" in args.partial:
            return (duration / playhead) * -(duration - playhead)  # weighted remaining
        elif "t" in args.partial:
            return -(duration - playhead)  # time remaining
        else:
            return playhead / duration  # percent remaining

    def sorting_hat():
        if "f" in args.partial:  # first-viewed
            return lambda m: m.get("time_first_played") or 0
        elif "p" in args.partial or "t" in args.partial:  # sort by remaining duration
            return mpv_progress

        return lambda m: m.get("time_last_played") or m.get("time_first_played") or 0

    reverse_chronology = True
    if "o" in args.partial:  # oldest first
        reverse_chronology = False

    key = sorting_hat()
    if args.print:
        reverse_chronology = not reverse_chronology

    media = sorted(
        media,
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


def find_none_keys(list_of_dicts, keep_0=True):
    none_keys = []

    if not list_of_dicts:
        return none_keys

    keys = list_of_dicts[0].keys()
    for key in keys:
        is_key_none = True
        for d in list_of_dicts:
            value = d.get(key)
            if value or (keep_0 and value == 0):
                is_key_none = False
                break
        if is_key_none:
            none_keys.append(key)

    return none_keys


def list_dict_filter_bool(media: List[dict], keep_0=True) -> List[dict]:
    keys_to_remove = find_none_keys(media, keep_0=keep_0)
    return [d for d in [{k: v for k, v in m.items() if k not in keys_to_remove} for m in media] if d]


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


def chunks(lst, n) -> Iterator:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def divisor_gen(n: int) -> Iterator:
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


def safe_unpack(*list_, idx=0, keep_0=True) -> Optional[Any]:
    list_ = conform(list_)
    if not list_:
        return None

    try:
        value = list_[idx]
        return value if keep_0 or value != 0 else None
    except IndexError:
        return None


def safe_sum(*list_, keep_0=False) -> Optional[Any]:
    list_ = conform(list_)
    if not list_:
        return None
    value = sum(list_)
    return value if keep_0 or value != 0 else None


def path_fill(text, percent=None, width=None):
    if percent:
        width = max(10, int(percent * (consts.TERMINAL_SIZE.columns / 80)))
    lines = []
    current_line = ""
    for char in str(text):
        if char == "\r":
            continue  # Ignore carriage return character
        elif char == "\n":
            lines.append(current_line)
            current_line = ""
        else:
            current_line += char
            if len(current_line) == width:
                lines.append(current_line)
                current_line = ""
    if current_line:
        lines.append(current_line)
    return "\n".join(lines)


def distribute_excess_width(max_col_widths, sep_char=4):
    existing_width = sum(max_col_widths.values()) + (len(max_col_widths) * sep_char)
    wide_cols = {
        k: width
        for k, width in max_col_widths.items()
        if width > 14 and k not in ("duration", "size", *consts.EPOCH_COLUMNS)
    }
    excess_width = 10 + existing_width - consts.TERMINAL_SIZE.columns

    if excess_width <= 0:
        return {}

    distributed_widths = {}
    for key, width in wide_cols.items():
        ratio = width / sum(wide_cols.values())
        subtract_width = math.ceil(ratio * excess_width)
        distributed_widths[key] = width - subtract_width

    return distributed_widths


def multi_split(string, delimiters):
    delimiters = tuple(delimiters)
    stack = [
        string,
    ]

    for delimiter in delimiters:
        for i, substring in enumerate(stack):
            substack = substring.split(delimiter)
            stack.pop(i)
            for j, _substring in enumerate(substack):
                stack.insert(i + j, _substring)

    return stack


def calculate_max_col_widths(data):
    max_col_widths = {}
    for row in data:
        for key, value in row.items():
            if isinstance(value, str):
                lines = value.splitlines()
                max_line_length = max(len(line) for line in lines or [""])
                max_col_widths[key] = max(max_col_widths.get(key, 0), max_line_length, len(key))
            elif isinstance(value, list):
                max_value_length = max(len(str(item)) for item in value)
                max_col_widths[key] = max(max_col_widths.get(key, 0), max_value_length)
            else:
                max_value_length = len(str(value))
                max_col_widths[key] = max(max_col_widths.get(key, 0), max_value_length)

    return max_col_widths


def col_resize(tbl: List[Dict], col: str, width) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = path_fill(tbl[idx][col], width=width)

    return tbl


def col_resize_percent(tbl: List[Dict], col: str, percent=10) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = path_fill(tbl[idx][col], percent=percent)

    return tbl


def col_naturaldate(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        val = tbl[idx].get(col)
        if val is not None:
            val = int(val)
            if val == 0:
                tbl[idx][col] = None
            else:
                tbl[idx][col] = humanize.naturaldate(datetime.fromtimestamp(val))

    return tbl


def col_naturaltime(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        val = tbl[idx].get(col)
        if val is not None:
            val = int(val)
            if val == 0:
                tbl[idx][col] = None
            else:
                tbl[idx][col] = humanize.naturaltime(datetime.fromtimestamp(val))

    return tbl


def col_naturalsize(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            if tbl[idx][col] == 0:
                tbl[idx][col] = None
            else:
                tbl[idx][col] = humanize.naturalsize(tbl[idx][col])

    return tbl


def human_time(seconds) -> str:
    if seconds is None or math.isnan(seconds) or seconds == 0:
        return ""

    test = humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="minutes", format="%0.0f")

    PRECISION_YEARS = 3
    if len(test.split(",")) >= PRECISION_YEARS:
        return humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="hours", format="%0.0f")

    PRECISION_MONTHS = 2
    if len(test.split(",")) >= PRECISION_MONTHS:
        return humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="hours", format="%0.0f")

    if int(seconds) > 10 * 60:
        return humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="minutes", format="%0.0f")

    return humanize.precisedelta(timedelta(seconds=int(seconds)), minimum_unit="seconds", format="%0.0f")


def col_duration(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = human_time(tbl[idx][col])
    return tbl


def seconds_to_hhmmss(seconds):
    if seconds < 0:
        seconds = abs(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if hours == 0:
        formatted_time = f"   {minutes:02d}:{seconds:02d}"

    return formatted_time


def col_hhmmss(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = seconds_to_hhmmss(tbl[idx][col])
    return tbl


class ArgparseList(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        items = getattr(namespace, self.dest, None) or []

        items.extend(values.split(","))  # type: ignore

        setattr(namespace, self.dest, items)


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


class ArgparseArgsOrStdin(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if values == ["-"]:
            lines = sys.stdin.readlines()
        else:
            lines = values
        setattr(namespace, self.dest, lines)


def filter_namespace(args, config_opts) -> Optional[Dict]:
    return dict_filter_bool({k: v for k, v in args.__dict__.items() if k in config_opts})


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
                random.shuffle(result_list)
                return result_list[:25][state]
            else:
                match_list = [s for s in list_ if s.startswith(line)]
                min_depth = min([s.count(os.sep) for s in match_list]) + 1
                result_list = [c + " " for c in match_list if c.count(os.sep) <= min_depth]
                random.shuffle(result_list)
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


def parse_human_to_lambda(human_to_x, sizes):
    return lambda var: all(
        (
            (var > human_to_x(size.lstrip(">")))
            if ">" in size
            else (var < human_to_x(size.lstrip("<")))
            if "<" in size
            else (var >= human_to_x(size.lstrip("+")))
            if "+" in size
            else (human_to_x(size.lstrip("-")) >= var)
            if "-" in size
            else (
                int(human_to_x(size) + (human_to_x(size) / 10))
                >= var
                >= int(human_to_x(size) - (human_to_x(size) / 10))
            )
        )
        for size in sizes
    )


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


def pipe_lines(x) -> None:
    try:
        sys.stdout.writelines(x)
    except BrokenPipeError:
        sys.stdout = None
        sys.exit(141)


def random_string() -> str:
    return "".join(
        random.choices(string.ascii_uppercase, k=1) + random.choices(string.ascii_uppercase + string.digits, k=4)
    )


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

    log.debug("mpv_playhead %s", mpv_playhead)
    log.debug("python_playhead %s", python_playhead)
    for playhead in [mpv_playhead or 0, python_playhead]:
        if playhead > 0 and (media_duration is None or media_duration >= playhead):
            return playhead
    return None


class Timer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time = default_timer()

    def elapsed(self):
        if not hasattr(self, "start_time"):
            raise RuntimeError("Timer has not been started.")
        end_time = default_timer()
        elapsed_time = end_time - self.start_time
        self.reset()
        return f"{elapsed_time:.4f}"


def cover_scan(media_duration, scan_percentage):
    num_scans = max(2, int(math.log(media_duration) * (scan_percentage / 10)))
    scan_duration_total = max(1, media_duration * (scan_percentage / 100))
    scan_duration = max(1, int(scan_duration_total / num_scans))
    scan_interval = media_duration / num_scans

    scans = sorted(set(int(scan * scan_interval) for scan in range(num_scans)))
    if scans[-1] < media_duration - (scan_duration * 2):
        scans.append(math.floor(media_duration - scan_duration))

    return scans, scan_duration


def fast_glob(path_dir, limit=100):
    files = []
    with os.scandir(path_dir) as entries:
        for entry in entries:
            if entry.is_file():
                files.append(entry.path)
                if len(files) == limit:
                    break
    return sorted(files)


def cluster_paths(paths, n_clusters=None):
    if len(paths) < 2:
        return paths

    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    sentence_strings = (path_to_sentence(s) for s in paths)

    try:
        vectorizer = TfidfVectorizer(min_df=2, strip_accents="unicode", stop_words="english")
        X = vectorizer.fit_transform(sentence_strings)
    except ValueError:
        try:
            vectorizer = TfidfVectorizer(strip_accents="unicode", stop_words="english")
            X = vectorizer.fit_transform(sentence_strings)
        except ValueError:
            try:
                vectorizer = TfidfVectorizer()
                X = vectorizer.fit_transform(sentence_strings)
            except ValueError:
                vectorizer = TfidfVectorizer(analyzer="char_wb")
                X = vectorizer.fit_transform(sentence_strings)

    clusterizer = KMeans(n_clusters=n_clusters or int(X.shape[0] ** 0.5), random_state=0, n_init=10).fit(X)
    clusters = clusterizer.labels_

    grouped_strings = {}
    for i, string in enumerate(paths):
        cluster_id = clusters[i]

        if cluster_id not in grouped_strings:
            grouped_strings[cluster_id] = []

        grouped_strings[cluster_id].append(string)

    result = []
    for _cluster_id, paths in grouped_strings.items():
        common_prefix = os.path.commonprefix(paths)
        metadata = {
            "common_prefix": common_prefix,
            "grouped_paths": sorted(paths),
        }
        result.append(metadata)

    return result


def cluster_images(paths, n_clusters=None):
    paths = [s.rstrip("\n") for s in paths]
    t = Timer()

    import os

    import numpy as np
    from annoy import AnnoyIndex
    from PIL import Image

    log.info("imports %s", t.elapsed())
    index_dir = "image_cluster_indexes"
    os.makedirs(index_dir, exist_ok=True)

    img_size = 100  # trade-off between accuracy and speed

    image_mode_groups = {}
    for path in paths:
        img = Image.open(path)
        img = img.resize((img_size, img_size), Image.Resampling.NEAREST)
        img_array = np.array(img).reshape(-1)  # convert to scalar for ANNoy
        mode = img.mode
        if mode not in image_mode_groups:
            image_mode_groups[mode] = []
        image_mode_groups[mode].append(img_array)
    log.info("image_mode_groups %s", t.elapsed())

    annoy_indexes = {}
    for mode, images in image_mode_groups.items():
        dimension = images[0].shape[0]

        annoy_index = AnnoyIndex(dimension, "angular")
        for i, vector in enumerate(images):
            annoy_index.add_item(i, vector)

        annoy_index.build(100)  # trade-off between accuracy and speed
        annoy_indexes[mode] = annoy_index
    log.info("annoy_index %s", t.elapsed())

    clusters = []
    for mode, images in image_mode_groups.items():
        annoy_index = annoy_indexes[mode]
        for i in range(len(images)):
            nearest_neighbors = annoy_index.get_nns_by_item(i, n_clusters or int(len(images) ** 0.6))
            clusters.extend([i] * len(nearest_neighbors))
    log.info("image_mode_groups %s", t.elapsed())

    grouped_strings = {}
    for i, string in enumerate(paths):
        cluster_id = clusters[i]

        if cluster_id not in grouped_strings:
            grouped_strings[cluster_id] = []

        grouped_strings[cluster_id].append(string + "\n")
    log.info("grouped_strings %s", t.elapsed())

    result = []
    for _cluster_id, paths in grouped_strings.items():
        common_prefix = os.path.commonprefix(paths)
        metadata = {
            "common_prefix": common_prefix,
            "grouped_paths": sorted(paths),
        }
        result.append(metadata)
    log.info("common_prefix %s", t.elapsed())

    return result


def cluster_dicts(args, media):
    if len(media) < 2:
        return media
    media_keyed = {d["path"]: d for d in media}
    groups = cluster_paths([d["path"] for d in media])
    groups = sorted(groups, key=lambda d: (-len(d["grouped_paths"]), -len(d["common_prefix"])))
    if hasattr(args, "sort") and "duration" in args.sort:
        sorted_paths = flatten(
            sorted(d["grouped_paths"], key=lambda p: media_keyed[p]["duration"], reverse="duration desc" in args.sort)
            for d in groups
        )
    else:
        sorted_paths = flatten(d["grouped_paths"] for d in groups)
    media = [media_keyed[p] for p in sorted_paths]
    return media


def is_timecode_like(text):
    for char in text:
        if not (char in ":,_-;. " or char.isdigit()):
            return False
    return True


def is_generic_title(title):
    return (
        (len(title) <= 12 and (title.startswith(("Chapter", "Scene"))))
        or "Untitled Chapter" in title
        or is_timecode_like(title)
        or title.isdigit()
    )


def write_csv_to_stdout(data):
    fieldnames = data[0].keys()
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(data)


def order_set(items):
    seen = set()
    for item in items:
        if item not in seen:
            yield item
            seen.add(item)


def partial_startswith(original_string, startswith_match_list):
    matching_strings = []

    candidate = deepcopy(original_string)
    while len(matching_strings) == 0 and len(candidate) > 0:
        for s in startswith_match_list:
            if s.startswith(candidate):
                matching_strings.append(s)

        if len(matching_strings) == 0:
            candidate = candidate[:-1]  # remove the last char

    if len(matching_strings) == 1:
        return matching_strings[0]
    else:
        msg = f"{original_string} does not match any of {startswith_match_list}"
        raise ValueError(msg)


def compare_block_strings(value, media_value):
    value = value.lower()
    media_value = media_value.lower()

    starts_with_wild = value.startswith("%")
    ends_with_wild = value.endswith("%")
    inner_value = value.lstrip("%").rstrip("%")
    inner_wild = "%" in inner_value

    if inner_wild:
        regex_pattern = value.replace("%", ".*")
        return bool(re.match(regex_pattern, media_value))
    elif not ends_with_wild and not starts_with_wild:
        return media_value.startswith(value)
    elif ends_with_wild and not starts_with_wild:
        return media_value.startswith(value.rstrip("%"))
    elif starts_with_wild and not ends_with_wild:
        return media_value.endswith(value.lstrip("%"))
    elif starts_with_wild and ends_with_wild:
        return inner_value in media_value
    raise ValueError("Unreachable?")


def is_blocked_dict_like_sql(m, blocklist):
    for block_dict in blocklist:
        for key, value in block_dict.items():
            if key in m and compare_block_strings(value, m[key]):
                return True
    return False


def block_dicts_like_sql(media, blocklist):
    return [m for m in media if not is_blocked_dict_like_sql(m, blocklist)]


def allow_dicts_like_sql(media, allowlist):
    allowed_media = []
    for m in media:
        is_blocked = False
        for block_dict in allowlist:
            for key, value in block_dict.items():
                if key in m and compare_block_strings(value, m[key]):
                    is_blocked = True
                    break
            if is_blocked:
                break
        if is_blocked:
            allowed_media.append(m)

    return allowed_media


def trim_path_segments(path, desired_length):
    path = Path(path)
    segments = [*list(path.parent.parts), path.stem]
    extension = path.suffix

    desired_length -= len(extension)

    while len("".join(segments)) > desired_length:
        longest_segment_index = max(range(len(segments)), key=lambda i: len(segments[i]))
        segments[longest_segment_index] = segments[longest_segment_index][:-1]

        if all(len(segment) % 2 == 0 for segment in segments):
            for i in range(len(segments)):
                segments[i] = segments[i][:-1]

    segments[-1] += extension
    return str(Path(*segments))


def rebin_folders(paths, max_files_per_folder=16000):
    parent_counts = Counter(Path(p).parent for p in paths)
    rebinned_tuples = []
    untouched = []
    parent_index = {}
    parent_current_count = {}

    for p in paths:
        path = Path(p)
        parent = path.parent
        if parent_counts[parent] > max_files_per_folder:
            if parent not in parent_index:
                parent_index[parent] = 1
                parent_current_count[parent] = 0

            min_len = math.floor(parent_counts[parent] / max_files_per_folder)
            rebinned_tuples.append((p, str(parent / str(parent_index[parent]).zfill(len(str(min_len))) / path.name)))
            parent_current_count[parent] += 1

            _quotient, remainder = divmod(parent_current_count[parent], max_files_per_folder)
            if remainder == 0:
                parent_index[parent] += 1
        else:
            untouched.append(p)

    return untouched, rebinned_tuples


def move_files(file_list):
    for existing_path, new_path in file_list:
        try:
            os.rename(existing_path, new_path)
        except Exception:
            try:
                parent_dir = os.path.dirname(new_path)
                os.makedirs(parent_dir, exist_ok=True)

                shutil.move(existing_path, new_path)
            except Exception:
                log.exception("Could not move %s", existing_path)


def move_files_bash(file_list):
    move_sh = """#!/bin/sh
existing_path=$1
new_path=$2

# Attempt to rename the file/directory
mv -Tn "$existing_path" "$new_path" 2>/dev/null

if [ $? -ne 0 ]; then
    mkdir -p $(dirname "$new_path")
    mv -Tn "$existing_path" "$new_path"
fi
"""
    move_sh_path = Path(tempfile.mktemp(dir=consts.TEMP_SCRIPT_DIR, prefix="move_", suffix=".sh"))
    move_sh_path.write_text(move_sh)
    move_sh_path.chmod(move_sh_path.stat().st_mode | 0o100)

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv") as temp:
        temp.writelines(
            f"{shlex.quote(existing_path)}\t{shlex.quote(new_path)}\n" for existing_path, new_path in file_list
        )
        temp.flush()
        os.fsync(temp.fileno())

        print(f"""### Move {len(file_list)} files to new folders: ###""")
        print(rf"PARALLEL_SHELL=sh parallel --colsep '\t' -a {temp.name} -j 20 {move_sh_path}")


def dumbcopy(d):
    return {i: j.copy() if type(j) == dict else j for i, j in d.items()}
