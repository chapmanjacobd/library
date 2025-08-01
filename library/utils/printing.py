import csv, itertools, math, sys, textwrap, time
from collections.abc import Callable
from datetime import datetime, timezone

import humanize
from tabulate import tabulate

from library.utils import consts, path_utils
from library.utils.strings import duration, duration_short, file_size, relative_datetime


def print_overwrite(*text, **kwargs):
    if "file" not in kwargs:
        kwargs["file"] = sys.stderr

    if consts.PYTEST_RUNNING or not sys.stdout.isatty():
        pass
    elif consts.IS_LINUX or consts.IS_MAC:
        print("\r" + text[0], *text[1:], end="\033[K", **kwargs)
    elif consts.IS_WINDOWS:
        print("\r" + text[0], *text[1:], end="", **kwargs)
    else:
        print(text, **kwargs)


def serialize_key(s):
    if isinstance(s, str):
        return s
    elif isinstance(s, tuple):
        return " ".join(s)
    return str(s)


def extended_view(iterable):
    print_index = True
    if isinstance(iterable, dict):
        print_index = False
        iterable = [iterable]

    if hasattr(iterable, "__iter__") and not hasattr(iterable, "__len__"):  # generator
        try:
            first_item = next(iter(iterable))
        except StopIteration:
            return  # if the generator is empty, return early
        iterable = itertools.chain([first_item], iterable)
        max_key_length = max(len(serialize_key(key)) for key in first_item.keys())
    else:
        max_key_length = max(len(serialize_key(key)) for item in iterable for key in item.keys())

    for index, item in enumerate(iterable, start=1):
        if print_index:
            print(f"-[ RECORD {index} ]-------------------------------------------------------------")
        for key, value in item.items():
            formatted_key = f"{serialize_key(key).ljust(max_key_length)} |"
            print(formatted_key, value)
        if print_index:
            print()


def table(tbl, **kwargs) -> None:
    table_text = tabulate(tbl, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False, **kwargs)
    if not table_text:
        return

    longest_line = max(len(s) for s in table_text.splitlines())
    try:
        if longest_line > consts.TERMINAL_SIZE.columns:
            extended_view(tbl)
        else:
            print(table_text)
    except BrokenPipeError:
        sys.stdout = None
        sys.exit(141)


def pipe_print(*args) -> None:
    try:
        print(*args, flush=True)
    except BrokenPipeError:
        sys.stdout = None
        sys.exit(141)


def pipe_lines(x) -> None:
    try:
        sys.stdout.writelines(x)  # must include line endings
    except BrokenPipeError:
        sys.stdout = None
        sys.exit(141)


def eta(cur_iter, max_iter, start_time=None):
    if start_time is None:
        start_time = consts.APPLICATION_START

    elapsed = time.time() - start_time
    estimated = (elapsed / max(cur_iter, 1)) * (max_iter)

    finish_time = start_time + estimated
    return "ETA: " + relative_datetime(finish_time)


def write_csv_to_stdout(data):
    fieldnames = data[0].keys()
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(data)


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


def transform_column(transform_func: Callable):
    def transform(tbl: list[dict], col: str, **kwargs) -> list[dict]:
        for d in tbl:
            if col in d and d[col] is not None:
                d[col] = transform_func(d[col], **kwargs)
        return tbl

    return transform


def transform_column_0null(transform_func: Callable):
    def transform(tbl: list[dict], col: str, **kwargs) -> list[dict]:
        for d in tbl:
            if col in d and d[col] is not None:
                if int(d[col]) == 0:
                    d[col] = None
                else:
                    d[col] = transform_func(d[col], **kwargs)
        return tbl

    return transform


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


def unquote_url(val: str) -> str:
    if val.startswith("http"):
        val = path_utils.safe_unquote(val)
    return val


col_duration = transform_column(duration)
col_duration_short = transform_column(duration_short)
col_hhmmss = transform_column(seconds_to_hhmmss)
col_unquote_url = transform_column(unquote_url)
col_resize = transform_column(path_fill)
col_resize_percent = transform_column(path_fill)

col_filesize = transform_column_0null(file_size)
col_naturaldate = transform_column_0null(
    lambda val: humanize.naturaldate(datetime.fromtimestamp(val, tz=timezone.utc).astimezone())
)
col_naturaltime = transform_column_0null(relative_datetime)


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
                max_col_widths[key] = max(max_col_widths.get(key) or 0, max_line_length, len(key))
            elif isinstance(value, list):
                max_value_length = max(len(str(item)) for item in value)
                max_col_widths[key] = max(max_col_widths.get(key) or 0, max_value_length)
            else:
                max_value_length = len(str(value))
                max_col_widths[key] = max(max_col_widths.get(key) or 0, max_value_length)

    return max_col_widths


def print_df(df):
    import pandas as pd

    if isinstance(df, pd.DataFrame):
        for col in df.select_dtypes(include=["category"]).columns:
            df[col] = df[col].astype("str")
    print()
    print(df.fillna("<NA>").to_markdown(tablefmt="github"))
    print()


def print_series(s):
    if len(s) > 0:
        print()
        print("\n".join([f"- {col}" for col in s]))
        print()
