from unittest import mock

from library.utils import path_utils
from tests import utils


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


@mock.patch("library.utils.consts.random_string", return_value="abcdef")
def test_random_filename(_mock_random_string):
    assert path_utils.random_filename("testfile.txt") == utils.p("testfile.abcdef.txt")
    assert path_utils.random_filename("/3_seconds_ago../Mike.webm") == utils.p("/3_seconds_ago../Mike.abcdef.webm")
    assert path_utils.random_filename("/test") == utils.p("/test.abcdef")
    assert path_utils.random_filename("/test./t") == utils.p("/test./t.abcdef")
    assert path_utils.random_filename("/.test") == utils.p("/.test.abcdef")
    assert path_utils.random_filename("/.test/t") == utils.p("/.test/t.abcdef")
    assert path_utils.random_filename("/test/thing something.txt") == utils.p("/test/thing something.abcdef.txt")


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
