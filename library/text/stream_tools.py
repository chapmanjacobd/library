import argparse
import re
import sys
from itertools import zip_longest

from library.utils import arggroups, argparse_utils

USAGE = {
    "group_lines": """library text group PATTERN [PATH ...]

    Group input lines by a regular-expression match. Capture groups are joined
    to form the group key; unmatched lines are placed in a separate group.
""",
    "interleave_lines": """library text interleave [PATH ...]

    Interleave lines from multiple files. With no paths, read one stream from stdin.
    Missing lines from shorter inputs are omitted.
""",
}


def _read_lines(path: str | None) -> list[str]:
    if not path or path == "-":
        return sys.stdin.readlines()
    with open(path, encoding="utf-8") as stream:
        return stream.readlines()


def _parser(usage: str) -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.debug(parser)
    return parser


def parse_group_lines_args() -> argparse.Namespace:
    parser = _parser(USAGE["group_lines"])
    parser.add_argument("pattern")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def group_lines() -> None:
    args = parse_group_lines_args()
    pattern = re.compile(args.pattern)
    groups: dict[str | None, list[str]] = {}

    for path in args.paths or [None]:
        for line in _read_lines(path):
            line = line.rstrip("\n")
            match = pattern.search(line)
            if match:
                key = "".join(group or "" for group in match.groups()) if match.groups() else match.group(0)
            else:
                key = None
            groups.setdefault(key, []).append(line)

    for key in sorted(groups, key=lambda value: "" if value is None else value):
        print(f"{key if key is not None else '(no match)'}:")
        print("\n".join(groups[key]))


def parse_interleave_lines_args() -> argparse.Namespace:
    parser = _parser(USAGE["interleave_lines"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def interleave_lines() -> None:
    args = parse_interleave_lines_args()
    paths = args.paths or ["-"]
    streams = [_read_lines(path) for path in paths]

    for row in zip_longest(*streams, fillvalue=None):
        for line in row:
            if line is not None:
                sys.stdout.write(line)
