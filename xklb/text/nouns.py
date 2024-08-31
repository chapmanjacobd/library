import itertools, pickle
from functools import wraps
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path

import regex

from xklb import usage
from xklb.data import wordbank
from xklb.utils import arggroups, argparse_utils, iterables, printing


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
    args = parser.parse_args()
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
        for char in "abcdefghijklmnopqrstuvwxyz":
            yield char
    else:
        for prefix in generate_strings(length - 1):
            for char in "abcdefghijklmnopqrstuvwxyz":
                yield prefix + char


def gen_or_str(append):
    append_gen = []
    if append:
        if append.isnumeric():
            append_gen = generate_strings(int(append))
        else:
            append_gen = [append]
    return append_gen


def check_dictionary(gen_func):
    with (Path(__file__).parent / ".." / "data" / "dictionary.pkl").open("rb") as f:
        dictionary = pickle.load(f)

    @wraps(gen_func)
    def wrapper(*args, **kwargs):
        for item in gen_func(*args, **kwargs):
            if item in dictionary:
                yield item

    return wrapper


def nouns() -> None:
    args = parse_args()

    def part_processor(args, parts):
        for part in parts:
            prepend_gen = gen_or_str(args.prepend)
            append_gen = gen_or_str(args.append)

            if prepend_gen and append_gen:
                for pre, post in itertools.product(prepend_gen, append_gen):
                    yield pre + part + post
            elif prepend_gen:
                for pre in prepend_gen:
                    yield pre + part
            elif append_gen:
                for post in append_gen:
                    yield part + post
            else:
                yield part

    if args.unique:
        part_processor = iterables.return_unique(part_processor)
    if not args.all:
        part_processor = check_dictionary(part_processor)

    for line in args.paths:
        if args.html_strip:
            txt = strip_tags(txt)

        parts = line_splitter(line)
        parts = part_processor(args, parts)
        for part in parts:
            printer(part)
