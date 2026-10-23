import os, sys, time
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from library.utils import nums, printing, processes, strings


@dataclass
class _MoveStats:
    count: int = 0
    size: int = 0


def _get_move_stats(args):
    stats = getattr(args, "_move_stats", None)
    if stats is None:
        stats = _MoveStats()
        args._move_stats = stats  # noqa: SLF001
    return stats


def add_time_filters(parser, prefix="move"):
    """Add time-based filtering arguments (ctime/mtime) to a parser.

    Args:
        parser: The argument parser or argument group
        prefix: Prefix for argument names (e.g., 'move' for --move-sizes)

    """
    prefix_dash = f"--{prefix}-" if prefix else "--"

    time_group = parser.add_argument_group("Time Filters")
    time_group.add_argument(
        f"{prefix_dash}time-created",
        action="append",
        default=[],
        help="""Constrain files by time_created (ctime)
--time-created='-3 days' (newer than)
--time-created='+3 days' (older than)""",
    )
    time_group.add_argument(
        f"{prefix_dash}created-within",
        action="append",
        default=[],
        help=f"""Constrain files by time_created (newer than)
{prefix_dash}created-within '3 days'""",
    )
    time_group.add_argument(
        f"{prefix_dash}created-before",
        action="append",
        default=[],
        help=f"""Constrain files by time_created (older than)
{prefix_dash}created-before '3 years'""",
    )
    time_group.add_argument(
        f"{prefix_dash}time-modified",
        action="append",
        default=[],
        help="""Constrain files by time_modified (mtime)
--time-modified='-3 days' (newer than)
--time-modified='+3 days' (older than)""",
    )
    time_group.add_argument(
        f"{prefix_dash}modified-within",
        f"{prefix_dash}changed-within",
        action="append",
        default=[],
        help=f"""Constrain files by time_modified (newer than)
{prefix_dash}modified-within '3 days'""",
    )
    time_group.add_argument(
        f"{prefix_dash}modified-before",
        f"{prefix_dash}changed-before",
        action="append",
        default=[],
        help=f"""Constrain files by time_modified (older than)
{prefix_dash}modified-before '3 years'""",
    )


def process_time_filters(args, prefix="move"):
    """Process time-based filtering arguments into filter functions.

    Args:
        args: Parsed arguments namespace
        prefix: Prefix for argument names (e.g., 'move' or empty)

    """
    prefix_underscore = f"{prefix}_" if prefix else ""
    now = time.time()

    # Process time-created arguments
    created_within = getattr(args, f"{prefix_underscore}created_within", [])
    created_before = getattr(args, f"{prefix_underscore}created_before", [])

    # Calculate threshold timestamps
    created_within_thresholds = [now - nums.human_to_seconds(s) for s in created_within]
    created_before_thresholds = [now - nums.human_to_seconds(s) for s in created_before]

    # Create filter function: timestamp must be >= all within thresholds AND < all before thresholds
    def time_created_filter(timestamp):
        if timestamp is None:
            return False
        for threshold in created_within_thresholds:
            if timestamp < threshold:
                return False
        for threshold in created_before_thresholds:
            if timestamp >= threshold:
                return False
        return True

    args.time_created = time_created_filter

    # Process time-modified arguments
    modified_within = getattr(args, f"{prefix_underscore}modified_within", [])
    modified_before = getattr(args, f"{prefix_underscore}modified_before", [])

    # Calculate threshold timestamps
    modified_within_thresholds = [now - nums.human_to_seconds(s) for s in modified_within]
    modified_before_thresholds = [now - nums.human_to_seconds(s) for s in modified_before]

    # Create filter function
    def time_modified_filter(timestamp):
        if timestamp is None:
            return False
        for threshold in modified_within_thresholds:
            if timestamp < threshold:
                return False
        for threshold in modified_before_thresholds:
            if timestamp >= threshold:
                return False
        return True

    args.time_modified = time_modified_filter


def _passes_file_filters(args, path, stat):
    return all(
        (
            not args.move_sizes or args.move_sizes(stat.st_size),
            not getattr(args, "time_created", None) or args.time_created(stat.st_ctime),
            not getattr(args, "time_modified", None) or args.time_modified(stat.st_mtime),
            not args.ext or path.lower().endswith(args.ext),
            not args.move_exclude or not any(fnmatch(path, s) for s in args.move_exclude),
            not args.move_include or any(fnmatch(path, s) for s in args.move_include),
        )
    )


def _check_move_limits(args, stat):
    if args.timeout_size and processes.sizeout(args.timeout_size, stat.st_size):
        print(f"\nReached sizeout... ({args.timeout_size})", file=sys.stderr)
        raise SystemExit(124)
    if args.move_limit and args.move_limit <= _get_move_stats(args).count:
        print(f"\nReached file move limit... ({args.move_limit})", file=sys.stderr)
        raise SystemExit(124)


def filter_src(args, path):
    # REMEMBER to exclude in merge-mv shortcut
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return False
    if not _passes_file_filters(args, path, stat):
        return False
    _check_move_limits(args, stat)
    return True


def print_stats(args, dest_path=None, file_size=None):
    stats = _get_move_stats(args)

    def file_plural(x):
        return "files" if x > 1 else "file"

    pr = print if args.simulate else printing.print_overwrite

    msg = [
        str(stats.count),
        " ",
        file_plural(stats.count),
        " ",
        "copied" if args.copy else "moved",
        " ",
        f"({strings.file_size(stats.size)})",
    ]
    if dest_path:
        msg.append(f"; {dest_path} ({strings.file_size(file_size)})")

    pr("".join(msg))


def track_moved(func):
    def wrapper(*args, **kwargs):
        if args[0].verbose == 0:
            return func(*args, **kwargs)
        stats = _get_move_stats(args[0])
        try:
            file_size = Path(args[1]).stat().st_size
        except FileNotFoundError:
            file_size = 0

        if not args[0].simulate:
            print_stats(args[0], args[2], file_size)
        try:
            result = func(*args, **kwargs)
            if result is not False:
                stats.size += file_size
                stats.count += 1
            return result
        finally:
            print_stats(args[0])

    return wrapper
