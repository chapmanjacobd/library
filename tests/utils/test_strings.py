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
    today = now + timedelta(minutes=5)
    assert strings.relative_datetime(today.timestamp()) == today.strftime("today, %H:%M")

    assert strings.relative_datetime(now.timestamp()) == now.strftime("today, %H:%M")

    today = now - timedelta(minutes=5)
    assert strings.relative_datetime(today.timestamp()) == today.strftime("today, %H:%M")

    earlier_today = now.replace(hour=10, minute=30)
    assert strings.relative_datetime(earlier_today.timestamp()) == earlier_today.strftime("today, %H:%M")


def test_relative_datetime_yesterday(now):
    yesterday = now - timedelta(days=1)
    assert strings.relative_datetime(yesterday.timestamp()) == yesterday.strftime("yesterday, %H:%M")


def test_relative_datetime_a_few_days_ago(now):
    days_ago = now - timedelta(days=5)
    assert strings.relative_datetime(days_ago.timestamp()) == days_ago.strftime("5 days ago, %H:%M")


def test_relative_datetime_long_time_ago(now):
    long_ago = now - timedelta(days=50)
    assert strings.relative_datetime(long_ago.timestamp()) == long_ago.strftime("%Y-%m-%d %H:%M")


def test_relative_datetime_tomorrow(now):
    tomorrow = now + timedelta(days=1)
    assert strings.relative_datetime(tomorrow.timestamp()) == tomorrow.strftime("tomorrow, %H:%M")


def test_relative_datetime_in_a_few_days(now):
    in_a_few_days = now + timedelta(days=5)
    assert strings.relative_datetime(in_a_few_days.timestamp()) == in_a_few_days.strftime("in 5 days, %H:%M")


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
