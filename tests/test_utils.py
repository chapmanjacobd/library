import os
from datetime import timezone
from pathlib import Path

from xklb import utils


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


def test_dict_filter_bool():
    assert utils.dict_filter_bool({"t": 0}) == {"t": 0}
    assert utils.dict_filter_bool({"t": 0}, keep_0=False) is None
    assert utils.dict_filter_bool({"t": 1}) == {"t": 1}
    assert utils.dict_filter_bool({"t": None, "t1": 1}) == {"t1": 1}
    assert utils.dict_filter_bool({"t": None}) is None
    assert utils.dict_filter_bool({"t": ""}) is None


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
    assert utils.col_naturaldate([{"t": 0, "t1": 1}], "t", tz=timezone.utc) == [{"t": "Jan 01 1970", "t1": 1}]
    assert utils.col_naturaldate([{"t": 946684800, "t1": 1}], "t", tz=timezone.utc) == [{"t": "Jan 01 2000", "t1": 1}]


def test_col_naturalsize():
    assert utils.col_naturalsize([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert utils.col_naturalsize([{"t": 946684800, "t1": 1}], "t") == [{"t": "946.7 MB", "t1": 1}]


def test_human_time():
    assert utils.human_time(0) is None
    assert utils.human_time(946684800) == "30 years and 7 days"


def test_col_duration():
    assert utils.col_duration([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert utils.col_duration([{"t": 946684800, "t1": 1}], "t") == [{"t": "30 years and 7 days", "t1": 1}]


def test_preserve_hierarchy():
    assert utils.preserve_hierarchy(os.sep * 1) == os.sep
    assert utils.preserve_hierarchy(os.sep * 2) == "_".join([os.sep for _ in range(2)])
    assert utils.preserve_hierarchy(os.sep * 3) == "_".join([os.sep for _ in range(3)])
    assert utils.preserve_hierarchy(os.sep * 4) == "_".join([os.sep for _ in range(4)])


def test_remove_consecutive():
    assert utils.remove_consecutive(os.sep) == os.sep
    assert utils.remove_consecutive("........", char=".") == "."
    assert utils.remove_consecutive("..", char=".") == "."
    assert utils.remove_consecutive("  ") == " "
    assert utils.remove_consecutive("  ", char=" ") == " "


def test_remove_consecutives():
    assert utils.remove_consecutives("  ", chars=[" "]) == " "
    assert utils.remove_consecutives(" ..   ", chars=[" ", "."]) == " . "


def test_remove_path_prefixes():
    assert utils.remove_path_prefixes(os.sep, [os.sep]) == os.sep
    assert utils.remove_path_prefixes("/tmp/_/", prefixes=["_"]) == "/tmp//"
    assert utils.remove_path_prefixes("/tmp/____/", prefixes=["_"]) == "/tmp//"
    assert utils.remove_path_prefixes("/tmp/_/__/_/", prefixes=["_"]) == "/tmp////"
    assert utils.remove_path_prefixes("/tmp/_ /_ / _/", prefixes=["_", " "]) == "/tmp////"
    assert utils.remove_path_prefixes("/_////", prefixes=["_"]) == "/////"


def test_remove_path_suffixes():
    assert utils.remove_path_suffixes(os.sep, [os.sep]) == os.sep
    assert utils.remove_path_suffixes("/tmp/_/", suffixes=["_"]) == "/tmp//"
    assert utils.remove_path_suffixes("/tmp/____/", suffixes=["_"]) == "/tmp//"
    assert utils.remove_path_suffixes("/tmp/_/__/_/", suffixes=["_"]) == "/tmp////"
    assert utils.remove_path_suffixes("/tmp/_ /_ / _/", suffixes=["_", " "]) == "/tmp////"
    assert utils.remove_path_prefixes("/_////", prefixes=["_"]) == "/////"


def test_remove_stem_suffixes():
    assert utils.remove_stem_suffixes("_", suffixes=["_"]) == ""
    assert utils.remove_stem_suffixes("to__", suffixes=["_"]) == "to"
    assert utils.remove_stem_suffixes("__", suffixes=[" "]) == "__"
    assert utils.remove_stem_suffixes("_ ", suffixes=["_", " "]) == ""
    assert utils.remove_stem_suffixes(" _", suffixes=["_", " "]) == ""
    assert utils.remove_stem_suffixes("_ _", suffixes=["_", " "]) == ""


def test_clean_string():
    assert utils.clean_string(os.sep) == os.sep
    assert utils.clean_string("/3_seconds_ago.../") == "/3_seconds_ago…/"
    assert utils.clean_string("/  /t") == "/ /t"
    assert utils.clean_string("_  _") == "__"
    assert utils.clean_string("_") == "_"
    assert utils.clean_string("~_[7].opus") == "~_[7].opus"
    assert utils.clean_string("/!?/") == "/?/"
    assert utils.clean_string("/_/~_[7].opus") == "/_/~_[7].opus"


def test_clean_path():
    def p(string):
        return str(Path(string))

    assert utils.clean_path(b"/3_seconds_ago.../Mike.webm") == p("/3_seconds_ago…/Mike.webm")
    assert utils.clean_path(b"/3_seconds_ago../Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path(b"/3_seconds_ago./Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path(b"/3_seconds_ago___/ Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path(b"/test") == p("/test")
    assert utils.clean_path(b"/test./t") == p("/test/t")
    assert utils.clean_path(b"/.test") == p("/.test")
    assert utils.clean_path(b"/.test/t") == p("/.test/t")
    assert utils.clean_path(b"/_test/t") == p("/_test/t")
    assert utils.clean_path(b"/_test/-t") == p("/_test/t")
    assert utils.clean_path(b"/_test/t-") == p("/_test/t")
    assert utils.clean_path(b"/test/\xff\xfeH") == p("/test/\\xff\\xfeH")
    assert utils.clean_path(b"/test/thing something.txt") == p("/test/thing something.txt")
    assert utils.clean_path(b"/test/thing something.txt", dot_space=True) == p("/test/thing.something.txt")
    assert utils.clean_path(b"/_/~_[7].opus") == p("/_/~_[7].opus")
    assert utils.clean_path(b"/__/~_[7].opus") == p("/_/~_[7].opus")
