import argparse
import datetime
import math
import os
import sys
from pathlib import Path

from library import usage
from library.utils import arggroups, argparse_utils, file_utils, shell_utils

MIN_OUTLIER_RECORDS = 2
LOCAL_TIMEZONE = datetime.datetime.now().astimezone().tzinfo


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def iter_file_paths(paths, extensions=None, exclude=None, exclude_dirs=None):
    extensions = tuple(str(extension).lower().lstrip(".") for extension in (extensions or ()))
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            if not extensions or path.suffix.lower().lstrip(".") in extensions:
                yield str(path)
            continue
        if not path.is_dir():
            message = f"search path is not a file or directory: {raw_path}"
            raise FileNotFoundError(message)

        files, _, _ = shell_utils.rglob(
            path,
            extensions=extensions,
            exclude=exclude,
            exclude_dirs=exclude_dirs,
            quiet=True,
        )
        yield from sorted(files)


def find_files(root: str, extensions=None, exclude=None, exclude_dirs=None) -> list[tuple[int, str]]:
    records = []
    for path in iter_file_paths([root], extensions=extensions, exclude=exclude, exclude_dirs=exclude_dirs):
        try:
            stats = file_utils.get_file_stats({"path": path})
        except OSError as error:
            print(f"modified-hist: cannot stat {path}: {error}", file=sys.stderr)
            continue
        if stats.get("size") is not None and stats.get("time_modified") is not None:
            records.append((stats["time_modified"], path))
    return sorted(records, key=lambda record: (record[0], record[1]))


def collect_records(paths, extensions=None, exclude=None, exclude_dirs=None) -> list[tuple[int, str]]:
    records = []
    for path in paths:
        records.extend(find_files(path, extensions=extensions, exclude=exclude, exclude_dirs=exclude_dirs))
    return sorted(records, key=lambda record: (record[0], record[1]))


def format_timestamp(timestamp: float, span: float) -> str:
    date = datetime.datetime.fromtimestamp(timestamp, tz=LOCAL_TIMEZONE)
    if span < 24 * 60 * 60:
        return date.strftime("%H:%M:%S")
    return date.strftime("%Y-%m-%d %H:%M:%S")


def quartile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("cannot calculate a quartile for an empty sequence")
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] + (values[upper] - values[lower]) * weight


def outlier_records(records: list[tuple[int, str]]) -> list[tuple[int, str]]:
    if len(records) < MIN_OUTLIER_RECORDS:
        return []

    values = sorted(timestamp for timestamp, _ in records)
    lower_quartile = quartile(values, 0.25)
    upper_quartile = quartile(values, 0.75)
    fence = 1.5 * (upper_quartile - lower_quartile)
    lower_fence = lower_quartile - fence
    upper_fence = upper_quartile + fence
    return [record for record in sorted(records) if record[0] < lower_fence or record[0] > upper_fence]


def print_outliers(records: list[tuple[int, str]]) -> None:
    for timestamp, path in outlier_records(records):
        date = datetime.datetime.fromtimestamp(timestamp, tz=LOCAL_TIMEZONE)
        print(f"{date:%Y-%m-%d %H:%M:%S}\t{path}")


def histogram_buckets(records: list[tuple[int, str]], intervals: int) -> tuple[list[float], list[int]]:
    if intervals < 1:
        raise ValueError("intervals must be greater than zero")
    if not records:
        return [], []

    values = [timestamp for timestamp, _ in records]
    first = min(values)
    last = max(values)
    span = last - first
    if span == 0:
        return [first], [len(records)]

    buckets = [0] * intervals
    for timestamp in values:
        bucket = min(int((timestamp - first) / span * intervals), intervals - 1)
        buckets[bucket] += 1

    if intervals == 1:
        labels = [first]
    else:
        labels = [first + span * index / (intervals - 1) for index in range(intervals)]
    return labels, buckets


def print_chart(records: list[tuple[int, str]], width: int, intervals: int) -> None:
    if not records:
        print("Matches: 0.")
        return

    values = [timestamp for timestamp, _ in records]
    first = min(values)
    last = max(values)
    span = last - first
    labels, buckets = histogram_buckets(records, intervals)
    maximum = max(buckets)
    count_width = max(3, len(str(maximum)))
    label_width = max(len(format_timestamp(label, span)) for label in labels)
    available_bar_width = max(1, width - label_width - count_width - 8)
    count_per_symbol = max(1, math.ceil(maximum / available_bar_width))

    print(f"Matches: {len(records)}.")
    print(f"Each ∎ represents a count of {count_per_symbol}")
    for label, count in zip(labels, buckets):
        bar = "∎" * math.ceil(count / count_per_symbol) if count else ""
        stamp = format_timestamp(label, span)
        print(f"[{stamp:>{label_width}}] [{count:>{count_width}}] {bar}")


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.modified_hist)
    parser.add_argument("-o", "--outliers", action="store_true")
    parser.add_argument("--width", type=positive_int, default=80)
    parser.add_argument("--intervals", type=positive_int, default=20)
    parser.add_argument(
        "--exclude",
        action=argparse_utils.ArgparseList,
        default=[],
        help="Exclude matching files or directories",
    )
    parser.add_argument(
        "--exclude-dir",
        "--exclude-dirs",
        dest="exclude_dirs",
        nargs="+",
        action="extend",
        default=[],
        help="Exclude matching directories and their contents while scanning recursively",
    )
    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser, required=False)

    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    return args


def modified_hist() -> None:
    args = parse_args()
    paths = args.paths or ["."]
    for path in paths:
        print(path)
        try:
            records = find_files(path, extensions=args.ext, exclude=args.exclude, exclude_dirs=args.exclude_dirs)
        except FileNotFoundError as error:
            print(f"modified-hist: {error}", file=sys.stderr)
            continue
        if args.outliers:
            print_outliers(records)
        else:
            print_chart(records, args.width, args.intervals)


modified_histogram = modified_hist
files_modified_hist = modified_hist
