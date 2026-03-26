import os, sys, time
from fnmatch import fnmatch
from pathlib import Path

from library.utils import nums, printing, processes, strings

MOVED_COUNT = 0
MOVED_SIZE = 0


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


def filter_src(args, path):
    # REMEMBER to exclude in merge-mv shortcut

    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return False
    if args.move_sizes and not args.move_sizes(stat.st_size):
        return False

    # Filter by time_created (ctime)
    if getattr(args, "time_created", None) and not args.time_created(stat.st_ctime):
        return False

    # Filter by time_modified (mtime)
    if getattr(args, "time_modified", None) and not args.time_modified(stat.st_mtime):
        return False

    if args.ext and not path.lower().endswith(args.ext):
        return False

    if args.move_exclude and any(fnmatch(path, s) for s in args.move_exclude):
        return False

    if args.move_include and not any(fnmatch(path, s) for s in args.move_include):
        return False

    if args.timeout_size and processes.sizeout(args.timeout_size, stat.st_size):
        print(f"\nReached sizeout... ({args.timeout_size})", file=sys.stderr)
        raise SystemExit(124)
    elif args.move_limit and args.move_limit <= MOVED_COUNT:
        print(f"\nReached file move limit... ({args.move_limit})", file=sys.stderr)
        raise SystemExit(124)

    return True


def print_stats(args, dest_path=None, file_size=None):
    def file_plural(x):
        return "files" if x > 1 else "file"

    pr = print if args.simulate else printing.print_overwrite

    msg = [
        str(MOVED_COUNT),
        " ",
        file_plural(MOVED_COUNT),
        " ",
        "copied" if args.copy else "moved",
        " ",
        f"({strings.file_size(MOVED_SIZE)})",
    ]
    if dest_path:
        msg.append(f"; {dest_path} ({strings.file_size(file_size)})")

    pr("".join(msg))


def track_moved(func):
    def wrapper(*args, **kwargs):
        if args[0].verbose == 0:
            func(*args, **kwargs)
        else:
            global MOVED_COUNT, MOVED_SIZE
            try:
                file_size = Path(args[1]).stat().st_size
            except FileNotFoundError:
                file_size = 0

            if not args[0].simulate:
                print_stats(args[0], args[2], file_size)
            try:
                func(*args, **kwargs)
                MOVED_SIZE += file_size
                MOVED_COUNT += 1
            finally:
                print_stats(args[0])

    return wrapper
