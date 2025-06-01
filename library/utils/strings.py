import functools, html, json, math, operator, re, sys, textwrap
from ast import literal_eval
from copy import deepcopy
from datetime import datetime, timedelta
from datetime import timezone as tz
from fnmatch import fnmatch
from itertools import zip_longest

import humanize
from wcwidth import wcswidth

from library.data import wordbank
from library.utils import consts, iterables, nums
from library.utils.log_utils import log


def safe_json_loads(s):
    if isinstance(s, bytes):
        return safe_json_loads(s.decode("utf-8", errors="replace"))
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # try replacing control chars
        return json.loads(re.sub(r"[\x00-\x1f\x7f-\x9f]", "", s))


def safe_json_load(path):
    with open(path, "rb") as file:
        binary_data = file.read()
    return safe_json_loads(binary_data.decode("utf-8", errors="replace"))


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


def remove_consecutive_whitespace(s) -> str:
    return " ".join(s.split())  # spaces, tabs, and newlines


def remove_excessive_linebreaks(text):
    text = text.replace("\r\n", "\n")

    # Remove any whitespace that surrounds newlines
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)

    # three or more linebreaks become two
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


@repeat_until_same
def strip_enclosing_quotes(s):
    if s is None or len(s) < 2:
        return s

    for q in ['"', "'", "＇", '"', "‛", "‟", "＂", "‚", "〞", "〝", "〟", "„", "⹂", "❟", "❜", "❛", "❝", "❞"]:
        if s[0] == q and s[-1] == q:
            return s[1:-1]

    ls = ["‘", "“", "❮", "‹", "«"]
    rs = ["’", "”", "❯", "›", "»"]
    for l, r in zip(ls, rs, strict=False):
        if s[0] == l and s[-1] == r:
            return s[1:-1]
    for r, l in zip(ls, rs, strict=False):
        if s[0] == l and s[-1] == r:
            return s[1:-1]

    return s


def un_paragraph(item):
    s = remove_consecutive_whitespace(item)
    s = re.sub(r"[“”‘’]", "'", s)
    s = re.sub(r"[‛‟„]", '"', s)
    s = re.sub(r"[…]", "...", s)
    s = strip_enclosing_quotes(s)
    return s


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
    p = re.sub(r"\x7F", "", p)
    p = html.unescape(p)
    p = (
        p.replace("&", "")
        .replace("＆", "")
        .replace("%", "")
        .replace("％", "")
        .replace("*", "")
        .replace("＊", "")
        .replace("$", "")
        .replace("＄", "")
        .replace("#", "")
        .replace("＃", "")
        .replace(" @", "")
        .replace("!", "")
        .replace("?", "")
        .replace("|", "")
        .replace("｜", "")
        .replace("^", "")
        .replace("'", "")
        .replace('"', "")
        .replace("＂", "")
        .replace(")", "")
        .replace(":", "")
        .replace("：", "")
        .replace("꞉", "")
        .replace(">", "")
        .replace("<", "")
        .replace("＞", "")
        .replace("＜", "")
        .replace("\\", " ")
        .replace("/", " ")
        .replace("／", " ")
        .replace("∕", " ")
        .replace("⁄", " ")
        .replace("﹨", " ")
        .replace("＼", " ")
        .replace("∖", " ")
        .replace("﹨", " ")
    )
    p = remove_consecutives(p, chars=["."])
    p = (
        p.replace("(", " ")
        .replace("-.", ".")
        .replace(" - ", " ")
        .replace("- ", " ")
        .replace(" -", " ")
        .replace(" _ ", "_")
        .replace(" _", "_")
        .replace("_ ", "_")
    )
    p = remove_consecutive_whitespace(p)

    if p in [".", ".."]:
        return ""

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


def extract_words(string):
    if not string:
        return None

    cleaned_string = re.sub(r"[^\w\s]", " ", string)
    words = [remove_consecutive_whitespace(s) for s in cleaned_string.split()]
    words = [
        s
        for s in words
        if not (s.lower() in wordbank.stop_words or s.lower() in wordbank.prepositions or nums.safe_int(s) is not None)
    ]
    return words


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


_RE_COMBINE_WHITESPACE = re.compile(r"\s+")


def combine(*list_) -> str | None:
    list_ = iterables.conform(list_)
    if not list_:
        return None
    if len(list_) == 1:
        return str(list_[0])

    no_comma = functools.reduce(operator.iadd, (str(s).split(",") for s in list_), [])
    no_semicolon = functools.reduce(operator.iadd, (s.split(";") for s in no_comma), [])
    no_double_space = [_RE_COMBINE_WHITESPACE.sub(" ", s).strip() for s in no_semicolon]
    no_unknown = [x for x in no_double_space if x.lower() not in ("unknown", "none", "und", "")]

    no_duplicates = list(dict.fromkeys(no_unknown))
    return ";".join(no_duplicates)


def shorten(s, width):
    if wcswidth(s) <= width:
        return s

    truncated = ""
    current_width = 0
    for char in s:
        char_width = wcswidth(char)
        if current_width + char_width > width:
            break
        truncated += char
        current_width += char_width

    return remove_suffixes(truncated, [" ", "-", "."]) + "…"


def from_timestamp_seconds(s: str):
    parts = s.split(":")
    while len(parts) < 3:
        parts.insert(0, "00")

    hours, minutes, seconds = parts
    return int(hours or "0") * 3600 + int(minutes or "0") * 60 + float(seconds or "0")


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


def partial_startswith(original_string, startswith_match_list):
    matching_strings = []

    candidate = deepcopy(original_string)
    while len(matching_strings) == 0 and len(candidate) > 0:
        matching_strings = [s for s in startswith_match_list if s.startswith(candidate)]

        if len(matching_strings) == 0:
            candidate = candidate[:-1]  # remove the last char

    if len(matching_strings) == 1:
        return matching_strings[0]
    else:
        msg = f"{original_string} does not match any of {startswith_match_list}"
        raise ValueError(msg)


def last_chars(candidate) -> str:
    remove_groups = re.split(r"([\W]+|\s+|Ep\d+|x\d+|\.\d+)", candidate)
    log.debug(remove_groups)

    remove_chars = ""
    number_of_groups = 1
    while len(remove_chars) < 1:
        remove_chars += remove_groups[-number_of_groups]
        number_of_groups += 1

    return remove_chars


def percent(v) -> str | None:
    if v in [None, ""]:
        return None
    try:
        return f"{v:.2%}"
    except Exception:
        return None


def load_string(s):
    try:
        return json.loads(s)
    except Exception:
        try:
            return literal_eval(s)
        except Exception:
            return s


def format_two_columns(text1, text2, width1=25, width2=75, left_gutter=2, middle_gutter=2, right_gutter=3):
    terminal_width = min(consts.TERMINAL_SIZE.columns, 120) - (left_gutter + middle_gutter + right_gutter)
    if text2:
        width1 = int(terminal_width * (width1 / (width1 + width2)))
        width2 = int(terminal_width * (width2 / (width1 + width2)))
    else:
        width1 = terminal_width

    wrapped_text1 = []
    for t in text1.strip().split("\n"):
        if len(t) <= width1:
            wrapped_text1.append(t)
        else:
            wrapped_text1.extend(textwrap.wrap(t, width=width1, break_on_hyphens=False))

    wrapped_text2 = []
    for t in text2.split("\n"):
        if len(t) <= width2:
            wrapped_text2.append(t)
        else:
            wrapped_text2.extend(textwrap.wrap(t, width=width2, break_on_hyphens=False))

    formatted_lines = [
        f"{' ' * left_gutter}{line1:<{width1}}{' ' * middle_gutter}{line2:<{width2}}{' ' * right_gutter}".rstrip()
        for line1, line2 in zip_longest(wrapped_text1, wrapped_text2, fillvalue="")
    ]

    return "\n".join(formatted_lines) + "\n"


def file_size(n):
    return humanize.naturalsize(n, binary=True).replace(" ", "")


def duration(seconds) -> str:
    if seconds is None or math.isnan(seconds) or seconds == 0:
        return ""

    try:
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
    except OverflowError:
        return ""


def duration_short(seconds, format_str="%0.1f") -> str:
    if seconds is None or math.isnan(seconds) or seconds == 0:
        return ""

    try:
        if seconds < 60:
            return f"{int(seconds)} seconds"

        minutes = seconds / 60
        if minutes < 1.1:
            return "1 minute"
        elif minutes < 60:
            return f"{format_str % minutes} minutes"

        hours = minutes / 60
        if hours < 1.1:
            return "1 hour"
        elif hours < 24:
            return f"{format_str % hours} hours"

        days = hours / 24
        if days < 1.1:
            return "1 day"
        return f"{format_str % days} days"
    except OverflowError:
        return ""


def relative_datetime(seconds) -> str:
    if seconds is None or math.isnan(seconds) or seconds == 0:
        return ""

    now = datetime.now(tz=tz.utc).astimezone()
    midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        dt = datetime.fromtimestamp(seconds, tz=tz.utc).astimezone()
    except ValueError:
        return ""
    delta = datetime.today().astimezone() - dt
    delta_days = (abs(delta.days) - 1) if delta.days < 0 else delta.days

    if dt >= midnight_today:
        if delta_days == 0:
            return dt.strftime("today, %H:%M")
        elif delta_days == 1:
            return dt.strftime("tomorrow, %H:%M")
        elif delta_days < 46:
            return dt.strftime(f"in {delta_days} days, %H:%M")

    elif dt >= midnight_today - timedelta(days=1):
        return dt.strftime("yesterday, %H:%M")
    elif delta_days < 46:
        return dt.strftime(f"{delta_days} days ago, %H:%M")

    return dt.strftime("%Y-%m-%d %H:%M")


def timezone(s):
    import zoneinfo

    try:
        return zoneinfo.ZoneInfo(s)
    except zoneinfo.ZoneInfoNotFoundError:
        for zone in sorted(zoneinfo.available_timezones()):
            print(zone)

        print(
            f"ZoneInfoNotFoundError: No time zone found with key {s}. Try one of the above! (on Windows you might need to pip install tzdata)",
            file=sys.stderr,
        )
        raise SystemExit(3)


def glob_match_any(search_terms, texts):
    if isinstance(search_terms, str):
        search_terms = [search_terms]
    if isinstance(texts, str):
        texts = [texts]

    if not search_terms or not texts:
        return False

    texts = [str(t).casefold() for t in texts if t]

    for search_term in search_terms:
        search_pattern = "*" + str(search_term).casefold() + "*"
        for text in texts:
            if fnmatch(text, search_pattern):
                return True

    return False


def glob_match_all(search_terms, texts):
    if isinstance(search_terms, str):
        search_terms = [search_terms]
    if isinstance(texts, str):
        texts = [texts]

    if not search_terms or not texts:
        return False

    processed_texts = [str(t).casefold() for t in texts if t]

    for search_term in search_terms:
        search_pattern = "*" + str(search_term).casefold() + "*"
        found_match = False
        for text in processed_texts:
            if fnmatch(text, search_pattern):
                found_match = True
                break

        # if after checking all texts, no match was found for the specific term
        if not found_match:
            return False

    return True


def output_filter(ignore_pattern: re.Pattern):
    def process_value(value):
        if isinstance(value, str):
            return ignore_pattern.sub("", value)
        return value

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)

            if isinstance(result, str):
                return process_value(result)
            elif isinstance(result, tuple):
                return tuple(process_value(item) for item in result)
            else:
                return result

        return wrapper

    return decorator
