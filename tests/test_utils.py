import argparse, os, time
from pathlib import Path
from unittest import mock

from xklb import consts, utils


def p(string):
    return str(Path(string))


def take5():
    num = 0
    while num < 5:
        yield num
        num += 1


def test_flatten():
    assert list(utils.flatten([[[[1]]]])) == [1]
    assert list(utils.flatten([[[[1]], [2]]])) == [1, 2]
    assert list(utils.flatten([[[["test"]]]])) == ["test"]
    assert list(utils.flatten(take5())) == [0, 1, 2, 3, 4]
    assert list(utils.flatten("")) == []
    assert list(utils.flatten([""])) == [""]
    assert list(utils.flatten([b"hello \xF0\x9F\x98\x81"])) == ["hello 😁"]
    assert list(utils.flatten("[[[[1]]]]")) == ["[", "[", "[", "[", "1", "]", "]", "]", "]"]
    assert list(utils.flatten(["[[[[1]]]]"])) == ["[[[[1]]]]"]


def test_conform():
    assert utils.conform([[[[1]]]]) == [1]
    assert utils.conform([[[[1]], [2]]]) == [1, 2]
    assert utils.conform([[[["test"]]]]) == ["test"]
    assert utils.conform(take5()) == [1, 2, 3, 4]
    assert utils.conform("") == []
    assert utils.conform([""]) == []
    assert utils.conform(b"hello \xF0\x9F\x98\x81") == ["hello 😁"]
    assert utils.conform("[[[[1]]]]") == ["[[[[1]]]]"]


def test_combine():
    assert utils.combine([[[[1]]]]) == "1"
    assert utils.combine([[[[1]], [2]]]) == "1;2"
    assert utils.combine(1, 2) == "1;2"
    assert utils.combine(1, [2]) == "1;2"
    assert utils.combine([[[["test"]]]]) == "test"
    assert utils.combine(take5()) == "1;2;3;4"
    assert utils.combine("") is None
    assert utils.combine([""]) is None
    assert utils.combine(b"hello \xF0\x9F\x98\x81", 1) == "hello 😁;1"
    assert utils.combine("[[[[1]]]]") == "[[[[1]]]]"


def test_safe_unpack():
    assert utils.safe_unpack(1, 2, 3, 4) == 1
    assert utils.safe_unpack([1, 2, 3, 4]) == 1
    assert utils.safe_unpack(None, "", 0, 1, 2, 3, 4) == 1
    assert utils.safe_unpack([None, 1]) == 1
    assert utils.safe_unpack([None]) is None
    assert utils.safe_unpack(None) is None


def test_dict_filter_bool():
    assert utils.dict_filter_bool({"t": 0}) == {"t": 0}
    assert utils.dict_filter_bool({"t": 0}, keep_0=False) is None
    assert utils.dict_filter_bool({"t": 1}) == {"t": 1}
    assert utils.dict_filter_bool({"t": None, "t1": 1}) == {"t1": 1}
    assert utils.dict_filter_bool({"t": None}) is None
    assert utils.dict_filter_bool({"t": ""}) is None
    assert utils.dict_filter_bool(None) is None


def test_list_dict_filter_bool():
    assert utils.list_dict_filter_bool([{"t": 1}]) == [{"t": 1}]
    assert utils.list_dict_filter_bool([{"t": None}]) == []
    assert utils.list_dict_filter_bool([]) == []
    assert utils.list_dict_filter_bool([{}]) == []


def test_chunks():
    assert list(utils.chunks([1, 2, 3], 1)) == [[1], [2], [3]]
    assert list(utils.chunks([1, 2, 3], 2)) == [[1, 2], [3]]
    assert list(utils.chunks([1, 2, 3], 4)) == [[1, 2, 3]]


def test_divisor_gen():
    for v in [0, 1, 2, 3, 5, 7]:
        assert list(utils.divisor_gen(v)) == []
    assert list(utils.divisor_gen(4)) == [2]
    assert list(utils.divisor_gen(6)) == [2, 3]
    assert list(utils.divisor_gen(8)) == [2, 4]
    assert list(utils.divisor_gen(9)) == [3]
    assert list(utils.divisor_gen(10)) == [2, 5]
    assert list(utils.divisor_gen(100)) == [2, 4, 5, 10, 20, 25, 50]


def test_col_naturaldate():
    assert utils.col_naturaldate([{"t": 0, "t1": 1}], "t") == [{"t": "Jan 01 1970", "t1": 1}]
    assert utils.col_naturaldate([{"t": 946684800, "t1": 1}], "t") == [{"t": "Jan 01 2000", "t1": 1}]


def test_col_naturalsize():
    assert utils.col_naturalsize([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert utils.col_naturalsize([{"t": 946684800, "t1": 1}], "t") == [{"t": "946.7 MB", "t1": 1}]


def test_human_to_bytes():
    assert [
        utils.human_to_bytes("30"),
        utils.human_to_bytes("30b"),
        utils.human_to_bytes("30kb"),
        utils.human_to_bytes("30mb"),
        utils.human_to_bytes("30gb"),
        utils.human_to_bytes("30tb"),
        utils.human_to_bytes("30TiB"),
        utils.human_to_bytes("30TB"),
        utils.human_to_bytes("3.5mb"),
        utils.human_to_bytes("3.5 mb"),
        utils.human_to_bytes("3.5 mib"),
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
    assert utils.human_to_seconds("30") == 1800
    assert utils.human_to_seconds("30s") == 30
    assert utils.human_to_seconds("30m") == 1800
    assert utils.human_to_seconds("30mins") == 1800
    assert utils.human_to_seconds("30h") == 3600 * 30
    assert utils.human_to_seconds("30 hour") == 3600 * 30
    assert utils.human_to_seconds("30hours") == 3600 * 30
    assert utils.human_to_seconds("1 week") == 86400 * 7
    assert utils.human_to_seconds("30d") == 86400 * 30
    assert utils.human_to_seconds("30 days") == 86400 * 30
    assert utils.human_to_seconds("3.5mo") == 9072000
    assert utils.human_to_seconds("3.5months") == 9072000
    assert utils.human_to_seconds("3.5 years") == 110376000
    assert utils.human_to_seconds("3.5y") == 110376000


def test_parse_size():
    result = utils.parse_human_to_sql(utils.human_to_bytes, "size", ["<10MB"])
    expected_result = "and size < 10485760 "
    assert result == expected_result

    result = utils.parse_human_to_sql(utils.human_to_bytes, "size", [">100KB", "<10MB"])
    expected_result = "and size > 102400 and size < 10485760 "
    assert result == expected_result

    result = utils.parse_human_to_sql(utils.human_to_bytes, "size", ["+100KB"])
    expected_result = "and size >= 102400 "
    assert result == expected_result

    result = utils.parse_human_to_sql(utils.human_to_bytes, "size", ["-10MB"])
    expected_result = "and 10485760 >= size "
    assert result == expected_result

    result = utils.parse_human_to_sql(utils.human_to_bytes, "size", ["100KB"])
    expected_result = "and 112640 >= size and size >= 92160 "
    assert result == expected_result


def test_parse_duration():
    result = utils.parse_human_to_sql(utils.human_to_seconds, "duration", ["<30s"])
    expected_result = "and duration < 30 "
    assert result == expected_result

    result = utils.parse_human_to_sql(utils.human_to_seconds, "duration", [">1min", "<30s"])
    expected_result = "and duration > 60 and duration < 30 "
    assert result == expected_result

    result = utils.parse_human_to_sql(utils.human_to_seconds, "duration", ["+1min"])
    expected_result = "and duration >= 60 "
    assert result == expected_result

    result = utils.parse_human_to_sql(utils.human_to_seconds, "duration", ["-30s"])
    expected_result = "and 30 >= duration "
    assert result == expected_result

    result = utils.parse_human_to_sql(utils.human_to_seconds, "duration", ["1min"])
    expected_result = "and 66 >= duration and duration >= 54 "
    assert result == expected_result


def test_human_time():
    assert utils.human_time(0) is None
    assert utils.human_time(946684800) == "30 years and 7 days"


def test_col_duration():
    assert utils.col_duration([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert utils.col_duration([{"t": 946684800, "t1": 1}], "t") == [{"t": "30 years and 7 days", "t1": 1}]


def test_remove_consecutive():
    assert utils.remove_consecutive(os.sep) == os.sep
    assert utils.remove_consecutive("........", char=".") == "."
    assert utils.remove_consecutive("..", char=".") == "."
    assert utils.remove_consecutive("  ") == " "
    assert utils.remove_consecutive("  ", char=" ") == " "


def test_remove_consecutives():
    assert utils.remove_consecutives("  ", chars=[" "]) == " "
    assert utils.remove_consecutives(" ..   ", chars=[" ", "."]) == " . "


def test_remove_prefixes():
    assert utils.remove_prefixes("-t", prefixes=["-"]) == "t"


def test_remove_suffixes():
    assert utils.remove_suffixes("_", suffixes=["_"]) == ""
    assert utils.remove_suffixes("to__", suffixes=["_"]) == "to"
    assert utils.remove_suffixes("__", suffixes=[" "]) == "__"
    assert utils.remove_suffixes("_ ", suffixes=["_", " "]) == ""
    assert utils.remove_suffixes(" _", suffixes=["_", " "]) == ""
    assert utils.remove_suffixes("_ _", suffixes=["_", " "]) == ""


def test_clean_string():
    assert utils.clean_string(os.sep) == os.sep
    assert utils.clean_string("/  /t") == "/ /t"
    assert utils.clean_string("_  _") == "__"
    assert utils.clean_string("_") == "_"
    assert utils.clean_string("~_[7].opus") == "~_[7].opus"
    assert utils.clean_string("/!./") == "/./"
    assert utils.clean_string("/_/~_[7].opus") == "/_/~_[7].opus"


def test_clean_path():
    assert utils.clean_path(b"/_test/-t") == p("/_test/t")
    assert utils.clean_path(b"/3_seconds_ago.../Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path(b"/3_seconds_ago../Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path(b"/3_seconds_ago./Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path(b"/3_seconds_ago___/ Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path(b"/test") == p("/test")
    assert utils.clean_path(b"/test./t") == p("/test/t")
    assert utils.clean_path(b"/.test") == p("/.test")
    assert utils.clean_path(b"/.test/t") == p("/.test/t")
    assert utils.clean_path(b"/_test/t") == p("/_test/t")
    assert utils.clean_path(b"/_test/t-") == p("/_test/t")
    assert utils.clean_path(b"/test/\xff\xfeH") == p("/test/\\xff\\xfeH")
    assert utils.clean_path(b"/test/thing something.txt") == p("/test/thing something.txt")
    assert utils.clean_path(b"/test/thing something.txt", dot_space=True) == p("/test/thing.something.txt")
    assert utils.clean_path(b"/_/~_[7].opus") == p("/_/~_[7].opus")
    assert utils.clean_path(b"/__/~_[7].opus") == p("/_/~_[7].opus")


@mock.patch("xklb.utils.random_string", return_value="abcdef")
def test_random_filename(_mock_random_string):
    assert utils.random_filename("testfile.txt") == p("testfile.abcdef.txt")
    assert utils.random_filename("/3_seconds_ago../Mike.webm") == p("/3_seconds_ago../Mike.abcdef.webm")
    assert utils.random_filename("/test") == p("/test.abcdef")
    assert utils.random_filename("/test./t") == p("/test./t.abcdef")
    assert utils.random_filename("/.test") == p("/.test.abcdef")
    assert utils.random_filename("/.test/t") == p("/.test/t.abcdef")
    assert utils.random_filename("/test/thing something.txt") == p("/test/thing something.abcdef.txt")


def test_mpv_md5():
    assert (
        utils.path_to_mpv_watchlater_md5("/home/xk/github/xk/lb/tests/data/test.mp4")
        == "E1E0D0E3F0D2CB748303FDA43224B7E7"
    )


def test_get_playhead():
    args = argparse.Namespace(
        mpv_socket=consts.DEFAULT_MPV_SOCKET,
        watch_later_directory=consts.DEFAULT_MPV_WATCH_LATER,
    )
    path = str(Path("tests/data/test.mp4").resolve())
    metadata_path = Path("~/.config/mpv/watch_later/E1E0D0E3F0D2CB748303FDA43224B7E7").expanduser().resolve()

    # use MPV time
    start_time = time.time() - 2
    Path(metadata_path).write_text("start=5.000000")
    assert utils.get_playhead(args, path, start_time) == 5
    # check invalid MPV time
    Path(metadata_path).write_text("start=13.000000")
    assert utils.get_playhead(args, path, start_time, media_duration=12) == 2

    # use python time
    Path(metadata_path).write_text("start=2.000000")
    start_time = time.time() - 4
    assert utils.get_playhead(args, path, start_time) == 4
    # check invalid python time
    start_time = time.time() - 13
    assert utils.get_playhead(args, path, start_time, media_duration=12) == 2
    # append existing time
    start_time = time.time() - 3
    assert utils.get_playhead(args, path, start_time, existing_playhead=4, media_duration=12) == 7
    # unless invalid
    assert utils.get_playhead(args, path, start_time, existing_playhead=10, media_duration=12) == 2
    start_time = time.time() - 10
    assert utils.get_playhead(args, path, start_time, existing_playhead=3, media_duration=12) == 2
