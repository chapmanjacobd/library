import sys
from html.parser import HTMLParser
from io import StringIO

from xklb.scripts.mining import data
from xklb.utils import pipe_print

"""
extract compound nouns and phrases from unstructured mixed HTML plain text

xsv select text hn_comment_202210242109.csv | library nouns | sort | uniq -c | sort --numeric-sort
"""


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


def printer(parts) -> None:
    for part in parts:
        part = part.strip()
        if not part:
            continue

        part_lookup = part.lower()
        if part_lookup in data.stop_words or part_lookup in data.prepositions or is_num(part):
            continue

        pipe_print(part)


def line_processor(txt) -> None:
    txt = strip_tags(txt)

    if getattr(line_processor, "RE_NOUNS_SPLIT", None) is None:
        import regex

        line_processor.RE_NOUNS_SPLIT = regex.compile(
            r"(?= [a-z]|(?<!\b[A-Z][a-z]*) (?=[A-Z]))|[.?!,\/#$%\^&\*;:{}=\-_`~()]|\,|\'|\"|\^|‘|’|“|”|\n| -| :| _",
        )

    parts = line_processor.RE_NOUNS_SPLIT.split(txt)
    printer(parts)


def nouns() -> None:
    for line in sys.stdin:
        line_processor(line)
