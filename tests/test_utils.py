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
    assert utils.col_naturaldate([{"t": 0, "t1": 1}], "t") == [{"t": "Jan 01 1970", "t1": 1}]
    assert utils.col_naturaldate([{"t": 946684800, "t1": 1}], "t") == [{"t": "Jan 01 2000", "t1": 1}]


def test_col_naturalsize():
    assert utils.col_naturalsize([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert utils.col_naturalsize([{"t": 946684800, "t1": 1}], "t") == [{"t": "946.7 MB", "t1": 1}]


def test_human_time():
    assert utils.human_time(0) is None
    assert utils.human_time(946684800) == "30 years and 7 days"


def test_col_duration():
    assert utils.col_duration([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert utils.col_duration([{"t": 946684800, "t1": 1}], "t") == [{"t": "30 years and 7 days", "t1": 1}]


def test_replace_consecutive():
    assert utils.replace_consecutive("........", char=".") == "."
    assert utils.replace_consecutive("..", char=".") == "."
    assert utils.replace_consecutive("  ") == " "
    assert utils.replace_consecutive("  ", char=" ") == " "


def test_clean_path():
    def p(string):
        return str(Path(string))

    assert utils.clean_path("/3_seconds_ago.../Mike.webm") == p("/3_seconds_ago…/Mike.webm")
    assert utils.clean_path("/3_seconds_ago../Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path("/3_seconds_ago./Mike.webm") == p("/3_seconds_ago/Mike.webm")
    assert utils.clean_path("/3_seconds_ago___/ Mike.webm") == p("/3_seconds_ago_/Mike.webm")
    assert utils.clean_path("/__init__.py") == p("/__init__.py")
    assert utils.clean_path("/test.") == p("/test")
