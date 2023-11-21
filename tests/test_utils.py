import argparse, os, time, unittest
from pathlib import Path
from unittest import mock

import pytest

from tests import utils
from xklb.media import av
from xklb.scripts import scatter
from xklb.utils import consts, iterables, mpv_utils, nums, objects, path_utils, printing, sql_utils, strings


def take5():
    num = 0
    while num < 5:
        yield num
        num += 1


def test_flatten():
    assert list(iterables.flatten([[[[1]]]])) == [1]
    assert list(iterables.flatten([[[[1]], [2]]])) == [1, 2]
    assert list(iterables.flatten([[[["test"]]]])) == ["test"]
    assert list(iterables.flatten(take5())) == [0, 1, 2, 3, 4]
    assert list(iterables.flatten("")) == []
    assert list(iterables.flatten([""])) == [""]
    assert list(iterables.flatten([b"hello \xF0\x9F\x98\x81"])) == ["hello 😁"]
    assert list(iterables.flatten("[[[[1]]]]")) == ["[", "[", "[", "[", "1", "]", "]", "]", "]"]
    assert list(iterables.flatten(["[[[[1]]]]"])) == ["[[[[1]]]]"]


def test_conform():
    assert iterables.conform([[[[1]]]]) == [1]
    assert iterables.conform([[[[1]], [2]]]) == [1, 2]
    assert iterables.conform([[[["test"]]]]) == ["test"]
    assert iterables.conform(take5()) == [1, 2, 3, 4]
    assert iterables.conform("") == []
    assert iterables.conform([""]) == []
    assert iterables.conform(b"hello \xF0\x9F\x98\x81") == ["hello 😁"]
    assert iterables.conform("[[[[1]]]]") == ["[[[[1]]]]"]


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


def test_safe_unpack():
    assert iterables.safe_unpack(1, 2, 3, 4) == 1
    assert iterables.safe_unpack([1, 2, 3, 4]) == 1
    assert iterables.safe_unpack(None, "", 0, 1, 2, 3, 4) == 1
    assert iterables.safe_unpack([None, 1]) == 1
    assert iterables.safe_unpack([None]) is None
    assert iterables.safe_unpack(None) is None


def test_safe_sum():
    assert iterables.safe_sum(1, 2, 3, 4) == 10
    assert iterables.safe_sum([1, 2, 3, 4]) == 10
    assert iterables.safe_sum(None, "", 0, 1, 2, 3, 4) == 10
    assert iterables.safe_sum([None, 1]) == 1
    assert iterables.safe_sum([None]) is None
    assert iterables.safe_sum(None) is None
    assert iterables.safe_sum() is None
    assert iterables.safe_sum([0, 0, 0]) is None


def test_dict_filter_bool():
    assert objects.dict_filter_bool({"t": 0}) == {"t": 0}
    assert objects.dict_filter_bool({"t": 0}, keep_0=False) is None
    assert objects.dict_filter_bool({"t": 1}) == {"t": 1}
    assert objects.dict_filter_bool({"t": None, "t1": 1}) == {"t1": 1}
    assert objects.dict_filter_bool({"t": None}) is None
    assert objects.dict_filter_bool({"t": ""}) is None
    assert objects.dict_filter_bool(None) is None


def test_list_dict_filter_bool():
    assert iterables.list_dict_filter_bool([{"t": 1}]) == [{"t": 1}]
    assert iterables.list_dict_filter_bool([{"t": None}]) == []
    assert iterables.list_dict_filter_bool([]) == []
    assert iterables.list_dict_filter_bool([{}]) == []


def test_chunks():
    assert list(iterables.chunks([1, 2, 3], 1)) == [[1], [2], [3]]
    assert list(iterables.chunks([1, 2, 3], 2)) == [[1, 2], [3]]
    assert list(iterables.chunks([1, 2, 3], 4)) == [[1, 2, 3]]


def test_divisor_gen():
    for v in [0, 1, 2, 3, 5, 7]:
        assert sorted(iterables.divisors_upto_sqrt(v)) == []
    assert sorted(iterables.divisors_upto_sqrt(4)) == [2]
    assert sorted(iterables.divisors_upto_sqrt(6)) == [2, 3]
    assert sorted(iterables.divisors_upto_sqrt(8)) == [2, 4]
    assert sorted(iterables.divisors_upto_sqrt(9)) == [3]
    assert sorted(iterables.divisors_upto_sqrt(10)) == [2, 5]
    assert sorted(iterables.divisors_upto_sqrt(100)) == [2, 4, 5, 10, 20, 25, 50]


def test_col_naturaldate():
    assert printing.col_naturaldate([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert printing.col_naturaldate([{"t": 0, "t1": 86399}], "t1") == [{"t": 0, "t1": "Jan 01 1970"}]


def test_col_naturalsize():
    assert printing.col_naturalsize([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert printing.col_naturalsize([{"t": 946684800, "t1": 1}], "t") == [{"t": "902.8 MiB", "t1": 1}]


def test_human_to_bytes():
    assert [
        nums.human_to_bytes("30"),
        nums.human_to_bytes("30b"),
        nums.human_to_bytes("30kb"),
        nums.human_to_bytes("30mb"),
        nums.human_to_bytes("30gb"),
        nums.human_to_bytes("30tb"),
        nums.human_to_bytes("30TiB"),
        nums.human_to_bytes("30TB"),
        nums.human_to_bytes("3.5mb"),
        nums.human_to_bytes("3.5 mb"),
        nums.human_to_bytes("3.5 mib"),
    ] == [
        31457280,
        30,
        30720,
        31457280,
        32212254720,
        32985348833280,
        32985348833280,
        32985348833280,
        3670016,
        3670016,
        3670016,
    ]


def test_human_to_seconds():
    assert nums.human_to_seconds("30") == 1800
    assert nums.human_to_seconds("30s") == 30
    assert nums.human_to_seconds("30m") == 1800
    assert nums.human_to_seconds("30mins") == 1800
    assert nums.human_to_seconds("30h") == 3600 * 30
    assert nums.human_to_seconds("30 hour") == 3600 * 30
    assert nums.human_to_seconds("30hours") == 3600 * 30
    assert nums.human_to_seconds("1 week") == 86400 * 7
    assert nums.human_to_seconds("30d") == 86400 * 30
    assert nums.human_to_seconds("30 days") == 86400 * 30
    assert nums.human_to_seconds("3.5mo") == 9072000
    assert nums.human_to_seconds("3.5months") == 9072000
    assert nums.human_to_seconds("3.5 years") == 110376000
    assert nums.human_to_seconds("3.5y") == 110376000


def test_parse_size():
    result = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", ["<10MB"])
    expected_result = "and size < 10485760 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", [">100KB", "<10MB"])
    expected_result = "and size > 102400 and size < 10485760 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", ["+100KB"])
    expected_result = "and size >= 102400 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", ["-10MB"])
    expected_result = "and 10485760 >= size "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", ["100KB"])
    expected_result = "and 112640 >= size and size >= 92160 "
    assert result == expected_result


def test_parse_duration():
    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["<30s"])
    expected_result = "and duration < 30 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", [">1min", "<30s"])
    expected_result = "and duration > 60 and duration < 30 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["+1min"])
    expected_result = "and duration >= 60 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["-30s"])
    expected_result = "and 30 >= duration "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["1min"])
    expected_result = "and 66 >= duration and duration >= 54 "
    assert result == expected_result


def test_human_time():
    assert printing.human_duration(0) == ""
    assert printing.human_duration(946684800) == "30 years and 7 days"


def test_col_duration():
    assert printing.col_duration([{"t": 0, "t1": 1}], "t") == [{"t": "", "t1": 1}]
    assert printing.col_duration([{"t": 946684800, "t1": 1}], "t") == [{"t": "30 years and 7 days", "t1": 1}]


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


def test_clean_path():
    assert path_utils.clean_path(b"_test/-t") == utils.p("_test/t")
    assert path_utils.clean_path(b"3_seconds_ago.../Mike.webm") == utils.p("3_seconds_ago/Mike.webm")
    assert path_utils.clean_path(b"3_seconds_ago../Mike.webm") == utils.p("3_seconds_ago/Mike.webm")
    assert path_utils.clean_path(b"3_seconds_ago./Mike.webm") == utils.p("3_seconds_ago/Mike.webm")
    assert path_utils.clean_path(b"3_seconds_ago___/ Mike.webm") == utils.p("3_seconds_ago/Mike.webm")
    assert path_utils.clean_path(b"test") == utils.p("test")
    assert path_utils.clean_path(b"test./t") == utils.p("test/t")
    assert path_utils.clean_path(b".test") == utils.p(".test")
    assert path_utils.clean_path(b".test/t") == utils.p(".test/t")
    assert path_utils.clean_path(b"_test/t") == utils.p("_test/t")
    assert path_utils.clean_path(b"_test/t-") == utils.p("_test/t")
    assert path_utils.clean_path(b"test/\xff\xfeH") == utils.p("test/\\xff\\xfeH")
    assert path_utils.clean_path(b"test/thing something.txt") == utils.p("test/thing something.txt")
    assert path_utils.clean_path(b"test/thing something.txt", dot_space=True) == utils.p("test/thing.something.txt")
    assert path_utils.clean_path(b"_/~_[7].opus") == utils.p("_/~_[7].opus")
    assert path_utils.clean_path(b"__/~_[7].opus") == utils.p("_/~_[7].opus")


@mock.patch("xklb.utils.consts.random_string", return_value="abcdef")
def test_random_filename(_mock_random_string):
    assert path_utils.random_filename("testfile.txt") == utils.p("testfile.abcdef.txt")
    assert path_utils.random_filename("/3_seconds_ago../Mike.webm") == utils.p("/3_seconds_ago../Mike.abcdef.webm")
    assert path_utils.random_filename("/test") == utils.p("/test.abcdef")
    assert path_utils.random_filename("/test./t") == utils.p("/test./t.abcdef")
    assert path_utils.random_filename("/.test") == utils.p("/.test.abcdef")
    assert path_utils.random_filename("/.test/t") == utils.p("/.test/t.abcdef")
    assert path_utils.random_filename("/test/thing something.txt") == utils.p("/test/thing something.abcdef.txt")


def test_mpv_md5():
    assert (
        mpv_utils.path_to_mpv_watchlater_md5("/home/xk/github/xk/lb/tests/data/test.mp4")
        == "E1E0D0E3F0D2CB748303FDA43224B7E7"
    )


def test_get_playhead():
    args = argparse.Namespace(
        mpv_socket=consts.DEFAULT_MPV_LISTEN_SOCKET,
        watch_later_directory=consts.DEFAULT_MPV_WATCH_LATER,
    )
    path = str(Path("/home/runner/work/library/library/tests/data/test.mp4").resolve())
    md5 = mpv_utils.path_to_mpv_watchlater_md5(path)
    metadata_path = Path(consts.DEFAULT_MPV_WATCH_LATER, md5).expanduser().resolve()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    # use MPV time
    start_time = time.time() - 2
    Path(metadata_path).write_text("start=5.000000")
    assert mpv_utils.get_playhead(args, path, start_time) == 5
    # check invalid MPV time
    Path(metadata_path).write_text("start=13.000000")
    assert mpv_utils.get_playhead(args, path, start_time, media_duration=12) == 2

    # use python time only if MPV does not exist
    assert mpv_utils.get_playhead(args, path, start_time) == 13
    Path(metadata_path).unlink()
    assert mpv_utils.get_playhead(args, path, start_time) == 2
    # append existing time
    start_time = time.time() - 3
    assert mpv_utils.get_playhead(args, path, start_time, existing_playhead=4, media_duration=12) == 7
    # unless invalid
    assert mpv_utils.get_playhead(args, path, start_time, existing_playhead=10, media_duration=12) is None
    start_time = time.time() - 10
    assert mpv_utils.get_playhead(args, path, start_time, existing_playhead=3, media_duration=12) is None


def scan_stats(scans, scan_duration):
    return (
        len(scans),  # number of scans
        scan_duration,  # duration of media scanned
        len(scans) * scan_duration,  # total scanned time
        0 if len(scans) == 1 else scans[1] - scan_duration,  # first gap time
    )


def test_cover_scan():
    assert scan_stats(*av.cover_scan(1, 0.01)) == (1, 1, 1, 0)
    assert scan_stats(*av.cover_scan(1, 100)) == (1, 1, 1, 0)

    result = [scan_stats(*av.cover_scan(5 * 60, percent)) for percent in [5, 10, 20, 30]]
    assert result == [(3, 7, 21, 143), (6, 6, 36, 54), (12, 5, 60, 22), (18, 5, 90, 12)]

    result = [scan_stats(*av.cover_scan(2 * 60 * 60, percent)) for percent in [5, 10, 20, 30]]
    assert result == [(5, 90, 450, 1710), (9, 90, 810, 810), (18, 84, 1512, 339), (27, 83, 2241, 193)]


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


class SecondsToHHMMSSTestCase(unittest.TestCase):
    def test_positive_seconds(self):
        assert printing.seconds_to_hhmmss(1) == "    0:01"
        assert printing.seconds_to_hhmmss(59) == "    0:59"
        assert printing.seconds_to_hhmmss(600) == "    10:00"
        assert printing.seconds_to_hhmmss(3600) == " 1:00:00"
        assert printing.seconds_to_hhmmss(3665) == " 1:01:05"
        assert printing.seconds_to_hhmmss(86399) == "23:59:59"
        assert printing.seconds_to_hhmmss(86400) == "24:00:00"
        assert printing.seconds_to_hhmmss(90061) == "25:01:01"

    def test_zero_seconds(self):
        assert printing.seconds_to_hhmmss(0) == "    0:00"


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


class TestStringComparison(unittest.TestCase):
    def test_compare_block_strings_starts_with(self):
        assert sql_utils.compare_block_strings("hello", "hello world")
        assert not sql_utils.compare_block_strings("world", "hello world")
        assert not sql_utils.compare_block_strings("abc", "hello world")

    def test_compare_block_strings_ends_with(self):
        assert sql_utils.compare_block_strings("%world", "hello world")
        assert sql_utils.compare_block_strings("hello", "hello world")
        assert not sql_utils.compare_block_strings("abc", "hello world")

    def test_compare_block_strings_contains(self):
        assert sql_utils.compare_block_strings("hello", "hello world")
        assert sql_utils.compare_block_strings("%world%", "hello world ok")
        assert sql_utils.compare_block_strings("hello world", "hello world")
        assert not sql_utils.compare_block_strings("abc", "hello world")

    def test_compare_block_strings_regex(self):
        assert sql_utils.compare_block_strings("he%o%", "hello world")
        assert sql_utils.compare_block_strings("%he%o%", " hello world")
        assert not sql_utils.compare_block_strings("%abc%", "hello world")
        assert sql_utils.compare_block_strings("h%o w%ld", "hello world")
        assert not sql_utils.compare_block_strings("abc", "hello world")
        assert sql_utils.compare_block_strings(None, None)
        assert not sql_utils.compare_block_strings(None, "hello world")
        assert not sql_utils.compare_block_strings("abc", None)


class TestBlocklist(unittest.TestCase):
    def setUp(self):
        self.media = [
            {"title": "Movie 1", "genre": "Action"},
            {"title": "Movie 2", "genre": "Comedy"},
            {"title": "Movie 3", "genre": "Drama"},
            {"title": "Movie 4", "genre": "Thriller"},
        ]

        self.blocklist = [{"genre": "Comedy"}, {"genre": "Thriller"}]

    def test_filter_dicts_genre(self):
        filtered_media = sql_utils.block_dicts_like_sql(self.media, self.blocklist)
        assert len(filtered_media) == 2
        assert {"title": "Movie 1", "genre": "Action"} in filtered_media
        assert {"title": "Movie 3", "genre": "Drama"} in filtered_media

    def test_filter_dicts_title(self):
        filtered_media = sql_utils.block_dicts_like_sql(self.media, [{"title": "Movie 1"}, {"title": "Movie 33"}])
        assert len(filtered_media) == 3
        assert {"title": "Movie 3", "genre": "Drama"} in filtered_media

    def test_filter_rows_with_substrings_contains(self):
        self.media.append({"title": "Movie 5", "genre": "Action Comedy"})
        filtered_media = sql_utils.block_dicts_like_sql(self.media, self.blocklist)
        assert len(filtered_media) == 3
        assert {"title": "Movie 5", "genre": "Action Comedy"} in filtered_media


class TestAllowlist(unittest.TestCase):
    def setUp(self):
        self.media = [
            {"title": "Movie 1", "genre": "Action"},
            {"title": "Movie 2", "genre": "Comedy"},
            {"title": "Movie 3", "genre": "Drama"},
            {"title": "Movie 4", "genre": "Thriller"},
        ]

        self.allowlist = [{"genre": "Comedy"}, {"genre": "Thriller"}]

    def test_filter_dicts_genre(self):
        filtered_media = sql_utils.allow_dicts_like_sql(self.media, self.allowlist)
        assert len(filtered_media) == 2

    def test_filter_dicts_title(self):
        filtered_media = sql_utils.allow_dicts_like_sql(self.media, [{"title": "Movie 1"}, {"title": "Movie 33"}])
        assert len(filtered_media) == 1

    def test_filter_rows_with_substrings_contains(self):
        self.media.append({"title": "Movie 5", "genre": "Action Comedy"})
        filtered_media = sql_utils.allow_dicts_like_sql(self.media, self.allowlist)
        assert len(filtered_media) == 2
        assert {"title": "Movie 5", "genre": "Action Comedy"} not in filtered_media


def test_trim_path_segments():
    path = "/aaaaaaaaaa/fans/001.jpg"
    desired_length = 16
    expected_result = "/aaaa/fans/001.jpg"
    assert path_utils.trim_path_segments(path, desired_length) == utils.p(expected_result)

    path = "/ao/bo/co/do/eo/fo/go/ho"
    desired_length = 9
    expected_result = "/a/b/c/d/e/f/g/h"
    assert path_utils.trim_path_segments(path, desired_length) == utils.p(expected_result)

    path = "/a/b/c"
    desired_length = 10
    expected_result = "/a/b/c"
    assert path_utils.trim_path_segments(path, desired_length) == utils.p(expected_result)


def test_rebin_folders():
    def dummy_folders(num_paths, base="/tmp/"):
        return [f"{base}{x}" for x in range(1, num_paths + 1)]

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5), 2)
    assert untouched == []
    expected = ["/tmp/1/1", "/tmp/1/2", "/tmp/2/3", "/tmp/2/4", "/tmp/3/5"]
    assert list(t[1] for t in rebinned) == [utils.p(s) for s in expected]

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5), 4)
    expected = ["/tmp/1/1", "/tmp/1/2", "/tmp/1/3", "/tmp/1/4", "/tmp/2/5"]
    assert list(t[1] for t in rebinned) == [utils.p(s) for s in expected]
    assert untouched == []

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5) + dummy_folders(5, "/tmp/f/"), 4)
    expected = [
        "/tmp/1/1",
        "/tmp/1/2",
        "/tmp/1/3",
        "/tmp/1/4",
        "/tmp/2/5",
        "/tmp/f/1/1",
        "/tmp/f/1/2",
        "/tmp/f/1/3",
        "/tmp/f/1/4",
        "/tmp/f/2/5",
    ]
    assert list(t[1] for t in rebinned) == [utils.p(s) for s in expected]
    assert untouched == []

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5) + dummy_folders(5, "/tmp/f/"), 5)
    assert rebinned == []
    assert len(untouched) == 10

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5) + dummy_folders(5, "/tmp/f/"), 6)
    assert rebinned == []
    assert len(untouched) == 10
