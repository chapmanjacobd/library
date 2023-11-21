import csv, math, os, platform, sys, textwrap
from datetime import datetime, time, timedelta
from typing import Dict, List

import humanize

from xklb.utils import consts


def print_overwrite(text):
    if os.name == "posix":
        print("\r" + text, end="\033[K", flush=True)
    elif platform.system() == "Windows":
        print("\r" + text, end="", flush=True)
    else:
        print(text)


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


def write_csv_to_stdout(data):
    fieldnames = data[0].keys()
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(data)


def human_duration(seconds) -> str:
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


def human_time(seconds) -> str:
    if seconds is None or math.isnan(seconds) or seconds == 0:
        return ""

    dt = datetime.fromtimestamp(seconds)
    delta = datetime.today() - dt

    midnight_today = datetime.combine(datetime.today(), time.min)
    midnight_yesterday = midnight_today - timedelta(days=1)

    if dt >= midnight_today:
        return dt.strftime("today, %H:%M")
    elif dt >= midnight_yesterday:
        return dt.strftime("yesterday, %H:%M")
    elif delta.days < 46:
        return datetime.fromtimestamp(seconds).strftime(f"{delta.days + 1} days ago, %H:%M")
    else:
        return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")


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
                tbl[idx][col] = human_time(val)

    return tbl


def col_naturalsize(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            if tbl[idx][col] == 0:
                tbl[idx][col] = None
            else:
                tbl[idx][col] = humanize.naturalsize(tbl[idx][col], binary=True)

    return tbl


def col_duration(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = human_duration(tbl[idx][col])
    return tbl


def wrap_paragraphs(text, width=80):
    paragraphs = text.split("\n\n")
    wrapped_paragraphs = [textwrap.fill(paragraph, width=width) for paragraph in paragraphs]
    formatted_text = "\n\n".join(wrapped_paragraphs)
    return formatted_text


def distribute_excess_width(max_col_widths, sep_char=4):
    existing_width = sum(max_col_widths.values()) + (len(max_col_widths) * sep_char)
    wide_cols = {
        k: width
        for k, width in max_col_widths.items()
        if width > 14 and k not in ("duration", "size", *consts.EPOCH_COLUMNS)
    }
    excess_width = 14 + existing_width - consts.TERMINAL_SIZE.columns

    if excess_width <= 0:
        return {}

    distributed_widths = {}
    for key, width in wide_cols.items():
        ratio = width / sum(wide_cols.values())
        subtract_width = math.ceil(ratio * excess_width)
        distributed_widths[key] = width - subtract_width

    return distributed_widths


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


def seconds_to_hhmmss(seconds):
    if seconds < 0:
        seconds = abs(seconds)
    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    formatted_time = f"{hours:>2}:{minutes:02d}:{seconds:02d}"
    if hours == 0:
        formatted_time = f"   {minutes:>2}:{seconds:02d}"

    return formatted_time


def col_hhmmss(tbl: List[Dict], col: str) -> List[Dict]:
    for idx, _d in enumerate(tbl):
        if tbl[idx].get(col) is not None:
            tbl[idx][col] = seconds_to_hhmmss(tbl[idx][col])
    return tbl


def print_df(df):
    print()
    print(df.to_markdown(tablefmt="github"))
    print()


def print_series(s):
    if len(s) > 0:
        print()
        print("\n".join([f"- {col}" for col in s]))
        print()
