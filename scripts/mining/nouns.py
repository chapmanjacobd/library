import sys
from html.parser import HTMLParser
from io import StringIO

import regex

from . import words

"""
extract compound nouns and phrases from unstructured mixed HTML plain text

xsv select text hn_comment_202210242109.csv | library nouns | sort | uniq -c | sort --numeric-sort
"""


class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()

    def handle_data(self, data):
        self.text.write(data)

    def get_data(self):
        return self.text.getvalue()


def strip_tags(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()


def is_num(s):
    return s.replace(".", "", 1).replace("-", "", 1).isdigit()


RE_NOUNS_SPLIT = regex.compile(
    r"(?= [a-z]|(?<!\b[A-Z][a-z]*) (?=[A-Z]))|[.?!,\/#$%\^&\*;:{}=\-_`~()]|\,|\'|\"|\^|‘|’|“|”|\n| -| :| _"
)


def printer(parts):
    for part in parts:
        part = part.strip()
        if not part:
            continue

        part_lookup = part.lower()
        if part_lookup in words.stop_words or part_lookup in words.prepositions or is_num(part):
            continue

        print(part)


def line_processor(txt):
    txt = strip_tags(txt)

    parts = RE_NOUNS_SPLIT.split(txt)
    printer(parts)


def nouns():
    for line in sys.stdin:
        line_processor(line)
