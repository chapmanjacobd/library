import math, os, unittest
from datetime import datetime, timedelta

import pytest
from dateutil import tz
from wcwidth import wcswidth

from library.utils import strings
from tests.utils import take5


def test_combine():
    assert strings.combine([[[[1]]]]) == "1"
    assert strings.combine([[[[1]], [2]]]) == "1;2"
    assert strings.combine(1, 2) == "1;2"
    assert strings.combine(1, [2]) == "1;2"
    assert strings.combine([[[["test"]]]]) == "test"
    assert strings.combine(take5()) == "1;2;3;4"
    assert strings.combine("") is None
    assert strings.combine([""]) is None
    assert strings.combine(b"hello \xf0\x9f\x98\x81", 1) == "hello 😁;1"
    assert strings.combine("[[[[1]]]]") == "[[[[1]]]]"


def test_remove_consecutive():
    assert strings.remove_consecutive(os.sep) == os.sep
    assert strings.remove_consecutive("........", char=".") == "."
    assert strings.remove_consecutive("..", char=".") == "."
    assert strings.remove_consecutive("  ") == " "
    assert strings.remove_consecutive("  ", char=" ") == " "


def test_remove_consecutives():
    assert strings.remove_consecutives("  ", chars=[" "]) == " "
    assert strings.remove_consecutives(" ..   ", chars=[" ", "."]) == " . "


def test_remove_prefixes():
    assert strings.remove_prefixes("-t", prefixes=["-"]) == "t"


def test_remove_suffixes():
    assert strings.remove_suffixes("_", suffixes=["_"]) == ""
    assert strings.remove_suffixes("to__", suffixes=["_"]) == "to"
    assert strings.remove_suffixes("__", suffixes=[" "]) == "__"
    assert strings.remove_suffixes("_ ", suffixes=["_", " "]) == ""
    assert strings.remove_suffixes(" _", suffixes=["_", " "]) == ""
    assert strings.remove_suffixes("_ _", suffixes=["_", " "]) == ""


def test_clean_string():
    assert strings.clean_string(os.sep) == ""
    assert strings.clean_string("/  /t") == "t"
    assert strings.clean_string("_  _") == "__"
    assert strings.clean_string("_") == "_"
    assert strings.clean_string("~_[7].opus") == "~_[7].opus"
    assert strings.clean_string("/!./") == ""
    assert strings.clean_string("/_/~_[7].opus") == "_~_[7].opus"


class TimecodeTestCase(unittest.TestCase):
    def test_valid_timecode(self):
        assert strings.is_timecode_like("12:34:56")
        assert strings.is_timecode_like("12,34,56")
        assert strings.is_timecode_like("12_34_56")
        assert strings.is_timecode_like("12;34;56")
        assert strings.is_timecode_like("12.34.56")
        assert strings.is_timecode_like("12-34-56")
        assert strings.is_timecode_like("12 34 56")
        assert strings.is_timecode_like("12:34:56.789")  # Contains a non-digit character (.)
        assert strings.is_timecode_like("12:34:56,")  # Contains a non-digit character (,)
        assert strings.is_timecode_like("12:34:56_")  # Contains a non-digit character (_)
        assert strings.is_timecode_like("12:34:56;")  # Contains a non-digit character (;)
        assert strings.is_timecode_like("12:34:56-")  # Contains a non-digit character (-)
        assert strings.is_timecode_like("12:34:56 ")  # Contains a non-digit character (space)
        assert strings.is_timecode_like("12:34:56.")  # Contains a non-digit character (.)
        assert strings.is_timecode_like("12:34:56,")  # Contains a non-digit character (,)
        assert strings.is_timecode_like("12:34:56_")  # Contains a non-digit character (_)
        assert strings.is_timecode_like("12:34:56;")  # Contains a non-digit character (;)
        assert strings.is_timecode_like("12:34:56-")  # Contains a non-digit character (-)
        assert strings.is_timecode_like("12:34:56 ")  # Contains a non-digit character (space)

    def test_invalid_timecode(self):
        assert not strings.is_timecode_like("12:34:56a")
        assert not strings.is_timecode_like("hello there")


def test_from_timestamp_seconds():
    assert strings.from_timestamp_seconds(":30") == 30.0
    assert strings.from_timestamp_seconds("0:30") == 30.0
    assert strings.from_timestamp_seconds("00:30") == 30.0
    assert strings.from_timestamp_seconds("1:") == 60.0
    assert strings.from_timestamp_seconds("1::") == 3600.0
    assert strings.from_timestamp_seconds("::1") == 1.0
    assert strings.from_timestamp_seconds(":1") == 1.0
    assert strings.from_timestamp_seconds("00:01:35") == 95.0
    assert strings.from_timestamp_seconds("00:00:00.001") == pytest.approx(0.001)
    assert strings.from_timestamp_seconds("01:00:00") == 3600.0
    assert strings.from_timestamp_seconds("01:00:00.1") == pytest.approx(3600.1)


class TestFindUnambiguousMatch(unittest.TestCase):
    def test_matching_string(self):
        my_string = "daily"
        my_list = ["daily", "weekly", "monthly", "yearly"]

        result = strings.partial_startswith(my_string, my_list)
        assert result == "daily"

    def test_partial_matching_string(self):
        my_string = "mon"
        my_list = ["monthly", "daily", "weekly", "yearly"]

        result = strings.partial_startswith(my_string, my_list)
        assert result == "monthly"

    def test_empty_list(self):
        my_string = "day"
        my_list = []

        with pytest.raises(ValueError):
            strings.partial_startswith(my_string, my_list)

    def test_empty_string(self):
        my_string = ""
        my_list = ["daily", "weekly", "monthly", "yearly"]

        with pytest.raises(ValueError):
            strings.partial_startswith(my_string, my_list)

    def test_no_matching_string(self):
        my_string = "hour"
        my_list = ["daily", "weekly", "monthly", "yearly"]

        with pytest.raises(ValueError):
            strings.partial_startswith(my_string, my_list)


def test_human_time():
    assert strings.duration(0) == ""
    assert strings.duration(946684800) == "30 years and 7 days"


@pytest.fixture
def now():
    return datetime.now(tz=tz.UTC).astimezone()


def test_relative_datetime_today(now):
    assert strings.relative_datetime(now.timestamp()) == now.strftime("today, %H:%M")

    specific_today = (now.replace(hour=10, minute=30)).astimezone()
    assert strings.relative_datetime(specific_today.timestamp()) == specific_today.strftime("today, 10:30")


def test_relative_datetime_yesterday(now):
    yesterday = (now - timedelta(days=1)).astimezone()
    assert strings.relative_datetime(yesterday.timestamp()) == yesterday.strftime("yesterday, %H:%M")


def test_relative_datetime_a_few_days_ago(now):
    days_ago = (now - timedelta(days=5)).astimezone()
    assert strings.relative_datetime(days_ago.timestamp()) == days_ago.strftime("5 days ago, %H:%M")


def test_relative_datetime_long_time_ago(now):
    long_ago = (now - timedelta(days=50)).astimezone()
    assert strings.relative_datetime(long_ago.timestamp()) == long_ago.strftime("%Y-%m-%d %H:%M")


def test_relative_datetime_tomorrow(now):
    tomorrow = (now + timedelta(days=1)).astimezone()
    assert strings.relative_datetime(tomorrow.timestamp()) == tomorrow.strftime("tomorrow, %H:%M")


def test_relative_datetime_in_a_few_days(now):
    in_a_few_days = (now + timedelta(days=5)).astimezone()
    result = strings.relative_datetime(in_a_few_days.timestamp())
    assert result == in_a_few_days.strftime("in 5 days, %H:%M")


def test_relative_datetime_long_future(now):
    long_future = (now + timedelta(days=50)).astimezone()
    assert strings.relative_datetime(long_future.timestamp()) == long_future.strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize("invalid_input", [None, math.nan, 0, 1e200])
def test_relative_datetime_invalid_inputs(invalid_input):
    assert strings.relative_datetime(invalid_input) == ""


@pytest.mark.parametrize(
    ("text", "max_width", "expected"),
    [
        ("hello", 10, "hello"),
        ("hello world", 10, "hell...rld"),
        ("abcdefghij", 8, "abc...ij"),
        ("abcdefghij", 7, "ab...ij"),
        ("abcdefghij", 6, "abc..."),
        ("abcdefghij", 5, "ab..."),
        ("abcdefghij", 4, "a..."),
        ("abcdefghij", 3, "..."),
        ("😀😃😄😁😆😅😂🤣😊😇", 11, "😀😃...😊😇"),
        ("😀😃😄😁😆😅😂🤣😊😇", 10, "😀😃...😇"),
        ("😀😃😄😁😆😅😂🤣😊😇", 9, "😀...😇"),
        ("😀😃😄😁😆😅😂🤣😊😇", 7, "😀...😇"),
        ("😀😃😄😁😆😅😂🤣😊😇", 6, "😀..."),
        ("😀😃😄😁😆😅😂🤣😊😇", 5, "😀..."),
        ("👨‍👩‍👧‍👦", 2, "👨‍👩‍👧‍👦"),
        ("👨‍👩‍👧‍👦", 1, "..."),
        ("👍🏽👍🏿👍🏻", 6, "👍🏽👍🏿👍🏻"),
        ("👍🏽👍🏿👍🏿👍🏿👍🏿👍🏿👍🏻", 10, "👍🏽👍🏿...👍🏻"),
        ("👍🏽👍🏿👍🏿👍🏿👍🏿👍🏿👍🏻", 9, "👍🏽...👍🏻"),
        ("👍🏽👍🏿👍🏿👍🏿👍🏿👍🏿👍🏻", 8, "👍🏽...👍🏻"),
        ("👍🏽👍🏿👍🏿👍🏿👍🏿👍🏿👍🏻", 7, "👍🏽...👍🏻"),
        ("👍🏽👍🏿👍🏿👍🏿👍🏿👍🏿👍🏻", 6, "👍🏽..."),
        ("🇺🇸🇨🇦🇩🇪", 6, "🇺🇸🇨🇦🇩🇪"),  # no ZWS
        ("🇺🇸🇨🇦🇨🇦🇨🇦🇨🇦🇩🇪", 8, "..."),
        ("🇺🇸\u200b🇨🇦\u200b🇩🇪", 6, "🇺🇸\u200b🇨🇦\u200b🇩🇪"),  # with ZWS
        ("🇺🇸\u200b🇨🇦\u200b\u200b🇨🇦\u200b🇨🇦\u200b🇨🇦\u200b🇩🇪", 9, "🇺🇸\u200b...\u200b🇩🇪"),
        ("🇺🇸\u200b🇨🇦\u200b\u200b🇨🇦\u200b🇨🇦\u200b🇨🇦\u200b🇩🇪", 8, "🇺🇸\u200b...\u200b🇩🇪"),
        ("🇺🇸\u200b🇨🇦\u200b\u200b🇨🇦\u200b🇨🇦\u200b🇨🇦\u200b🇩🇪", 7, "🇺🇸\u200b...\u200b🇩🇪"),
        ("🇺🇸\u200b🇨🇦\u200b\u200b🇨🇦\u200b🇨🇦\u200b🇨🇦\u200b🇩🇪", 6, "🇺🇸\u200b..."),
        ("🇺🇸\u200b🇨🇦\u200b\u200b🇨🇦\u200b🇨🇦\u200b🇨🇦\u200b🇩🇪", 5, "🇺🇸\u200b..."),
        ("#️⃣", 2, "#️⃣"),
        ("#️⃣", 1, "..."),
        ("✌🏿", 2, "✌🏿"),
    ],
)
def test_shorten_middle(text, max_width, expected):
    result = strings.shorten_middle(text, max_width)
    assert result == expected
    assert wcswidth(result) <= max_width or expected == "..."


def test_safe_json_loads():
    assert strings.safe_json_loads('{"a": 1}') == {"a": 1}
    assert strings.safe_json_loads(b'{"a": 1}') == {"a": 1}
    assert strings.safe_json_loads('{"a": 1\x00}') == {"a": 1}  # Control char removal


def test_remove_excessive_linebreaks():
    assert strings.remove_excessive_linebreaks("a\r\nb") == "a\nb"
    assert strings.remove_excessive_linebreaks("a \n b") == "a\nb"
    assert strings.remove_excessive_linebreaks("a\n\n\nb") == "a\n\nb"


def test_strip_enclosing_quotes():
    assert strings.strip_enclosing_quotes('"hello"') == "hello"
    assert strings.strip_enclosing_quotes("'hello'") == "hello"
    assert strings.strip_enclosing_quotes("“hello”") == "hello"
    assert strings.strip_enclosing_quotes("hello") == "hello"


def test_un_paragraph():
    assert strings.un_paragraph("“hello”  world…") == "'hello' world..."


def test_path_to_sentence():
    assert strings.path_to_sentence("path/to/file.txt") == "path to file txt"
    assert strings.path_to_sentence("file_name-1.txt") == "file name 1 txt"


def test_extract_words():
    # "Hello" and "World" might be in stop_words/prepositions, using simpler unique words or checking logic
    # Assuming extract_words filters common words.
    assert strings.extract_words("UniqueTerm, AnotherTerm!") == ["UniqueTerm", "AnotherTerm"]
    assert strings.extract_words("Hello 123") == []  # Numbers are filtered, Hello might be stopped
    assert strings.extract_words("") is None


def test_remove_text_inside_brackets():
    assert strings.remove_text_inside_brackets("Hello (World)") == "Hello "
    assert strings.remove_text_inside_brackets("Hello [World]") == "Hello "
    assert strings.remove_text_inside_brackets("Hello") == "Hello"


def test_last_chars():
    assert strings.last_chars("Series.S01.1080p") == "1080p"


def test_percent():
    assert strings.percent(0.5) == "50.00%"
    assert strings.percent(None) is None
    assert strings.percent("") is None


def test_load_string():
    assert strings.load_string('{"a": 1}') == {"a": 1}
    assert strings.load_string("{'a': 1}") == {"a": 1}  # literal_eval
    assert strings.load_string("just string") == "just string"


def test_file_size():
    assert strings.file_size(1024) == "1.0KiB"


def test_duration_short():
    assert strings.duration_short(30) == "30 seconds"
    assert strings.duration_short(70) == "1.2 minutes"
    assert strings.duration_short(4000) == "1.1 hours"
    assert strings.duration_short(100000) == "1.2 days"
    assert strings.duration_short(0) == ""


def test_glob_match_any():
    assert strings.glob_match_any("test", ["this is a test"])
    assert not strings.glob_match_any("foo", ["bar"])
    assert strings.glob_match_any(["foo", "bar"], ["bar"])


def test_glob_match_all():
    assert strings.glob_match_all(["foo", "bar"], ["foo", "bar"])
    assert not strings.glob_match_all(["foo", "baz"], ["foo", "bar"])
    assert strings.glob_match_all("foo", "foo")
