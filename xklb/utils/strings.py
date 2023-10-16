import html, re
from copy import deepcopy
from typing import Optional

from xklb.data import wordbank
from xklb.utils import iterables, nums
from xklb.utils.log_utils import log


def repeat_until_same(fn):  # noqa: ANN201
    def wrapper(*args, **kwargs):
        p = args[0]
        while True:
            p1 = p
            p = fn(p, *args[1:], **kwargs)
            # print(fn.__name__, p)
            if p1 == p:
                break
        return p

    return wrapper


def remove_consecutive_whitespace(s) -> str:
    return " ".join(s.split())  # spaces, tabs, and newlines


def remove_consecutive(s, char=" ") -> str:
    return re.sub("\\" + char + "+", char, s)


@repeat_until_same
def remove_consecutives(s, chars) -> str:
    for char in chars:
        s = remove_consecutive(s, char)
    return s


@repeat_until_same
def remove_prefixes(s, prefixes) -> str:
    for prefix in prefixes:
        if s.startswith(prefix):
            s = s.replace(prefix, "", 1)
    return s


@repeat_until_same
def remove_suffixes(s, suffixes) -> str:
    for suffix in suffixes:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


@repeat_until_same
def clean_string(p) -> str:
    p = re.sub(r"\x7F", "", p)
    p = html.unescape(p)
    p = (
        p.replace("*", "")
        .replace("&", "")
        .replace("%", "")
        .replace("$", "")
        .replace("#", "")
        .replace(" @", "")
        .replace("!", "")
        .replace("?", "")
        .replace("|", "")
        .replace("^", "")
        .replace("'", "")
        .replace('"', "")
        .replace(")", "")
        .replace(":", "")
        .replace(">", "")
        .replace("<", "")
    )
    p = remove_consecutives(p, chars=["."])
    p = (
        p.replace("(", " ")
        .replace("-.", ".")
        .replace(" - ", " ")
        .replace("- ", " ")
        .replace(" -", " ")
        .replace(" _ ", "_")
        .replace(" _", "_")
        .replace("_ ", "_")
    )
    p = remove_consecutive_whitespace(p)
    return p


def path_to_sentence(s):
    return remove_consecutive_whitespace(
        s.replace("/", " ")
        .replace("\\", " ")
        .replace(".", " ")
        .replace("[", " ")
        .replace("(", " ")
        .replace("]", " ")
        .replace(")", " ")
        .replace("{", " ")
        .replace("}", " ")
        .replace("_", " ")
        .replace("-", " "),
    )


def extract_words(string):
    if not string:
        return None

    cleaned_string = re.sub(r"[^\w\s]", " ", string)
    words = [remove_consecutive_whitespace(s) for s in cleaned_string.split()]
    words = [
        s
        for s in words
        if not (s.lower() in wordbank.stop_words or s.lower() in wordbank.prepositions or nums.safe_int(s) is not None)
    ]
    return words


def remove_text_inside_brackets(text: str, brackets="()[]") -> str:  # thanks @jfs
    count = [0] * (len(brackets) // 2)  # count open/close brackets
    saved_chars = []
    for character in text:
        for i, b in enumerate(brackets):
            if character == b:  # found bracket
                kind, is_close = divmod(i, 2)
                count[kind] += (-1) ** is_close  # `+1`: open, `-1`: close
                if count[kind] < 0:  # unbalanced bracket
                    count[kind] = 0  # keep it
                else:  # found bracket to remove
                    break
        else:  # character is not a [balanced] bracket
            if not any(count):  # outside brackets
                saved_chars.append(character)
    return "".join(saved_chars)


_RE_COMBINE_WHITESPACE = re.compile(r"\s+")


def combine(*list_) -> Optional[str]:
    list_ = iterables.conform(list_)
    if not list_:
        return None

    no_comma = sum((str(s).split(",") for s in list_), [])
    no_semicolon = sum((s.split(";") for s in no_comma), [])
    no_double_space = [_RE_COMBINE_WHITESPACE.sub(" ", s).strip() for s in no_semicolon]
    no_unknown = [x for x in no_double_space if x.lower() not in ("unknown", "none", "und", "")]

    no_duplicates = list(dict.fromkeys(no_unknown))
    return ";".join(no_duplicates)


def is_timecode_like(text):
    for char in text:
        if not (char in ":,_-;. " or char.isdigit()):
            return False
    return True


def is_generic_title(title):
    return (
        (len(title) <= 12 and (title.startswith(("Chapter", "Scene"))))
        or "Untitled Chapter" in title
        or is_timecode_like(title)
        or title.isdigit()
    )


def partial_startswith(original_string, startswith_match_list):
    matching_strings = []

    candidate = deepcopy(original_string)
    while len(matching_strings) == 0 and len(candidate) > 0:
        for s in startswith_match_list:
            if s.startswith(candidate):
                matching_strings.append(s)

        if len(matching_strings) == 0:
            candidate = candidate[:-1]  # remove the last char

    if len(matching_strings) == 1:
        return matching_strings[0]
    else:
        msg = f"{original_string} does not match any of {startswith_match_list}"
        raise ValueError(msg)


def last_chars(candidate) -> str:
    remove_groups = re.split(r"([\W]+|\s+|Ep\d+|x\d+|\.\d+)", candidate)
    log.debug(remove_groups)

    remove_chars = ""
    number_of_groups = 1
    while len(remove_chars) < 1:
        remove_chars += remove_groups[-number_of_groups]
        number_of_groups += 1

    return remove_chars
