import itertools, pickle
from functools import wraps
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path

import regex

from library import usage
from library.data import wordbank
from library.utils import arggroups, argparse_utils, iterables, printing
import string


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.nouns)
    parser.add_argument("--html-strip", "--strip-html", action="store_true", help="Strip HTML tags")
    parser.add_argument("--unique", "-u", action="store_true", help="Deduplicate output")
    parser.add_argument("--all", "-a", action="store_true", help="Show all output, even non-dictionary words")
    parser.add_argument(
        "--prepend",
        default=False,
        const="1",
        nargs="?",
        help="Characters to prepend to outputs. Numbers are A-Z combinatorial",
    )
    parser.add_argument(
        "--append",
        default=False,
        const="1",
        nargs="?",
        help="Characters to append to outputs. Numbers are A-Z combinatorial",
    )
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    return args


RE_NOUNS_SPLIT = regex.compile(
    r"(?= [a-z]|(?<!\b[A-Z][a-z]*) (?=[A-Z]))|[.?!,\/#$%\^&\*;:{}=\-_`~()]|\,|\'|\"|\^|‘|’|“|”|\n| -| :| _",
)


class MLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()

    def handle_data(self, data) -> None:
        self.text.write(data)

    def get_data(self) -> str:
        return self.text.getvalue()


def strip_tags(html) -> str:
    s = MLStripper()
    s.feed(html)
    return s.get_data()


def is_num(s) -> bool:
    return s.replace(".", "", 1).replace("-", "", 1).isdigit()


def printer(part) -> None:
    if not part:
        return

    part_lookup = part.lower()
    if part_lookup in wordbank.stop_words or part_lookup in wordbank.prepositions or is_num(part):
        return

    printing.pipe_print(part)


def line_splitter(txt):
    parts = RE_NOUNS_SPLIT.split(txt)
    return [s.strip() for s in parts if s.strip()]


def generate_strings(length):
    if length == 1:
        for char in string.ascii_lowercase:
            yield char
    else:
        for prefix in generate_strings(length - 1):
            for char in string.ascii_lowercase:
                yield prefix + char


def _append_parts(args, part, dictionary):
    if not args.append:
        return []
    if not args.append.isnumeric():
        return [args.append]

    append = int(args.append)
    if args.all:
        return generate_strings(append)
    return sorted(
        s.split(part, 1)[1]
        for s in dictionary
        if s.startswith(part) and len(s) == len(part) + append
    )


def _prepend_parts(args, part, dictionary):
    if not args.prepend:
        return []
    if not args.prepend.isnumeric():
        return [args.prepend]

    prepend = int(args.prepend)
    if args.all:
        return generate_strings(prepend)
    return sorted(
        s.rsplit(part, 1)[0]
        for s in dictionary
        if s.endswith(part) and len(s) == len(part) + prepend
    )


def _process_part(args, part, dictionary):
    append_gen = _append_parts(args, part, dictionary)
    prepend_gen = _prepend_parts(args, part, dictionary)

    if prepend_gen and append_gen:
        yield from (pre + part + post for pre, post in itertools.product(prepend_gen, append_gen))
    elif prepend_gen:
        yield from (pre + part for pre in prepend_gen)
    elif append_gen:
        yield from (part + post for post in append_gen)
    else:
        yield part


def nouns() -> None:
    args = parse_args()

    dictionary = ()
    if not args.all:
        with (Path(__file__).parent / ".." / "data" / "dictionary.pkl").open("rb") as f:
            dictionary = pickle.load(f)  # noqa: S301 - this is a bundled, read-only application asset

    def part_processor(args, parts):
        for part in parts:
            yield from _process_part(args, part, dictionary)

    if args.unique:
        part_processor = iterables.return_unique(part_processor)
    if not args.all:
        part_processor_fn = part_processor

        @wraps(part_processor_fn)
        def check_dictionary(*args, **kwargs):
            for item in part_processor_fn(*args, **kwargs):
                if item in dictionary:
                    yield item

        part_processor = check_dictionary

    for raw_line in args.paths:
        line = raw_line
        if args.html_strip:
            line = strip_tags(line)

        parts = line_splitter(line)
        parts = part_processor(args, parts)
        for part in parts:
            printer(part)
