import os, unittest

import pytest

from tests.utils import take5
from library.utils import strings


def test_combine():
    assert strings.combine([[[[1]]]]) == "1"
    assert strings.combine([[[[1]], [2]]]) == "1;2"
    assert strings.combine(1, 2) == "1;2"
    assert strings.combine(1, [2]) == "1;2"
    assert strings.combine([[[["test"]]]]) == "test"
    assert strings.combine(take5()) == "1;2;3;4"
    assert strings.combine("") is None
    assert strings.combine([""]) is None
    assert strings.combine(b"hello \xF0\x9F\x98\x81", 1) == "hello 😁;1"
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
    assert strings.clean_string(os.sep) == os.sep
    assert strings.clean_string("/  /t") == "/ /t"
    assert strings.clean_string("_  _") == "__"
    assert strings.clean_string("_") == "_"
    assert strings.clean_string("~_[7].opus") == "~_[7].opus"
    assert strings.clean_string("/!./") == "/./"
    assert strings.clean_string("/_/~_[7].opus") == "/_/~_[7].opus"


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
