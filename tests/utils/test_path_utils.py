from unittest import mock

import pytest

from library.utils import consts, path_utils
from tests import utils


@pytest.mark.parametrize(
    ("mock_mountpoint", "src", "dest", "expected"),
    [
        ("/home/user", "/home/user/project/a/b/c", "../../../x/y/z", "/home/user/x/y/z/c/"),
        ("/var/home/user", "/var/home/user/project/a/b/c", "../../../x/y/z", "/var/home/user/x/y/z/c/"),
        ("/home/user", "/home/user/project/a/b/c", "../../../../x/y/z", "/home/user/x/y/z"),
        ("/home/user", "/home/user/project/a/b/c", "x/y/z", "/home/user/x/y/z/project/a/b/c/"),
        ("/home/user", "/home/user/project/a/b/c", "/abs/path/x/y/z", "/abs/path/x/y/z/project/a/b/c"),
        ("/", "/a/b/c", "../../../x/y/z", "/x/y/z"),
        ("/home/user", "/a/b/c", "../../../x/y/z", "/home/user/x/y/z"),
        ("/home/user", "/home/user/a", "../b/c", "/home/user/b/c"),
        ("/home/user", "/home/user/a/b", "../../c/d", "/home/user/c/d"),
        ("/home/user", "/home/user", "../a/b", "/home/user/a/b"),
        ("/home/user", "/home/user/a/b/c", "/x/y/z", "/x/y/z/a/b/c"),
        ("/mnt/data", "/mnt/data/a/b/c", "../x/y", "/mnt/data/x/y/b/c"),
        ("/mnt/data", "/mnt/data/a/b/c", "../../../x/y/z", "/mnt/data/x/y/z"),
    ],
)
def test_relative_from_mountpoint(mock_mountpoint, src, dest, expected):
    with mock.patch("library.utils.path_utils.mountpoint") as mock_mp:
        mock_mp.return_value = mock_mountpoint

        result = path_utils.relative_from_mountpoint(src, dest)
        assert utils.p(result) == utils.p(expected)


def test_clean_path():
    assert path_utils.clean_path(b"_test/-t") == utils.p("_test/t")
    assert path_utils.clean_path(b"3_seconds_ago.../Mike.webm") == utils.p("3_seconds_ago/Mike.webm")
    assert path_utils.clean_path(b"3_seconds_ago../Mike.webm") == utils.p("3_seconds_ago/Mike.webm")
    assert path_utils.clean_path(b"3_seconds_ago./Mike.webm") == utils.p("3_seconds_ago/Mike.webm")
    assert path_utils.clean_path(b"3_seconds_ago___/ Mike.webm") == utils.p("3_seconds_ago/Mike.webm")
    assert path_utils.clean_path(b"test") == utils.p("test")
    assert path_utils.clean_path(b"test./t") == utils.p("test/t")
    assert path_utils.clean_path(b"test//t") == utils.p("test/t")
    assert path_utils.clean_path(b"test/''/t") == utils.p("test/_/t")
    assert path_utils.clean_path(b".test") == utils.p(".test")
    assert path_utils.clean_path(b".test/t") == utils.p(".test/t")
    assert path_utils.clean_path(b"_test/t") == utils.p("_test/t")
    assert path_utils.clean_path(b"_test/t-") == utils.p("_test/t")
    assert path_utils.clean_path(b"test/thing something.txt") == utils.p("test/thing something.txt")
    assert path_utils.clean_path(b"test/thing something.txt", dot_space=True) == utils.p("test/thing.something.txt")
    assert path_utils.clean_path(b"_/~_[7].opus") == utils.p("_/~_[7].opus")
    assert path_utils.clean_path(b"__/~_[7].opus") == utils.p("_/~_[7].opus")

    if consts.IS_WINDOWS:
        assert path_utils.clean_path(b"test/\xff\xfeH") == utils.p("test\\xff\\xfeH")
    else:
        assert path_utils.clean_path(b"test/\xff\xfeH") == utils.p("test/xff xfeH")


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


@pytest.mark.parametrize(
    ("user_path", "expected"),
    [
        ("etc/passwd", "/path/to/fakeroot/etc/passwd"),
        ("var/log/app.log", "/path/to/fakeroot/var/log/app.log"),
        ("../../etc/passwd", "/path/to/fakeroot/etc/passwd"),
        ("/absolute/path/outside/fakeroot", "/path/to/fakeroot/absolute/path/outside/fakeroot"),
        ("..", "/path/to/fakeroot"),
        (".//./config/...", "/path/to/fakeroot/config/..."),
        ("a/b/c/../../d", "/path/to/fakeroot/a/d"),
    ],
)
def test_safe_join(user_path, expected):
    base_path = "/path/to/fakeroot"

    result = path_utils.safe_join(base_path, user_path)
    assert utils.p(result) == utils.p(expected)


@pytest.mark.parametrize(
    ("url", "expected_parent_path", "expected_filename"),
    [
        ("http://example.com/path/to/file.txt", "example.com/path/to", "file.txt"),
        ("http://example.com/.././../../path/to/file.txt", "example.com/path/to", "file.txt"),
        ("http://example.com/../path/./../../to/file.txt", "example.com/to", "file.txt"),
        ("https://www.example.org/another/file.jpg", "www.example.org/another", "file.jpg"),
        ("ftp://fileserver.net/pub/document.pdf", "fileserver.net/pub", "document.pdf"),
        ("http://example.com/", "example.com", ""),  # Root path, no filename
        ("http://example.com/path/", "example.com", "path"),  # Path ending in slash
        ("http://example.com//file.txt", "example.com", "file.txt"),  # Double slash in path
        ("http://example.com/file%20with%20space.txt", "example.com", "file with space.txt"),  # URL encoded space
        ("http://example.com/file+with+plus.txt", "example.com", "file+with+plus.txt"),  # Plus sign
        ("http://example.com/file-with-dash.txt", "example.com", "file-with-dash.txt"),  # Dash sign
        ("http://example.com/file_with_underscore.txt", "example.com", "file_with_underscore.txt"),  # Underscore
        ("http://example.com/file.with.dots.txt", "example.com", "file.with.dots.txt"),  # Dots in filename
        ("http://example.com/path/to/file", "example.com/path/to", "file"),  # No extension
        ("http://example.com/very/long/path/to/a/file.txt", "example.com/very/long/path/to/a", "file.txt"),
        ("http://example.com", "example.com", ""),  # Just the domain, no path
        ("http://example.com/?query=string", "example.com", ""),  # URL with query string, no path
        ("http://example.com/#fragment", "example.com", ""),  # URL with fragment, no path
        (
            "http://example.com/path/to/file.txt?query=string",
            "example.com/path/to",
            "file.txt",
        ),  # URL with query string and path
        (
            "http://example.com/path/to/file.txt#fragment",
            "example.com/path/to",
            "file.txt",
        ),  # URL with fragment and path
        (
            "http://example.com/path/to/file.txt?query=string#fragment",
            "example.com/path/to",
            "file.txt",
        ),  # URL with all parts
        ("file:///path/to/local/file.txt", "path/to/local", "file.txt"),  # File URL
        (
            "file://localhost/path/to/local/file.txt",
            "localhost/path/to/local",
            "file.txt",
        ),  # File URL with localhost netloc
        # ("file:///C:/path/to/windows/file.txt", "C:/path/to/windows", "file.txt"), # File URL with Windows path
        ("//example.com/path/file.txt", "example.com/path", "file.txt"),  # URL starting with // (protocol-relative)
        (
            "example.com/path/file.txt",
            "example.com/path",
            "file.txt",
        ),  #  URL without scheme (might be interpreted as relative path, depending on context of urlparse)
        (
            "/path/to/file.txt",
            "path/to",
            "file.txt",
        ),  # URL with absolute path only (no netloc) - might behave unexpectedly depending on urlparse behavior
        (
            "/../.././../path/to/file.txt",
            "path/to",
            "file.txt",
        ),  # URL with absolute path only (no netloc) - might behave unexpectedly depending on urlparse behavior
        (
            "path/to/file.txt",
            "path/to",
            "file.txt",
        ),  # URL with relative path only (no netloc or scheme) -  might behave unexpectedly depending on urlparse behavior
        ("http://example.com/path/to/.hidden_file", "example.com/path/to", ".hidden_file"),  # Hidden file (dot prefix)
        (
            "http://example.com/path/to/file with spaces.txt",
            "example.com/path/to",
            "file with spaces.txt",
        ),  # Filename with spaces (not URL encoded in path part)
        (
            "http://user:password@example.com/path/to/file.txt",
            "user.password@example.com/path/to",
            "file.txt",
        ),  # URL with authentication
        ("http://[::1]/path/to/file.txt", "[..1]/path/to", "file.txt"),  # IPv6 address as netloc
        ("http://127.0.0.1/path/to/file.txt", "127.0.0.1/path/to", "file.txt"),  # IPv4 address as netloc
        (
            "http://bücher.example.com/path/to/file.txt",
            "bücher.example.com/path/to",
            "file.txt",
        ),  # URL with non-ASCII domain (IDN - Internationalized Domain Name) -  Might need encoding handling if your environment doesn't support IDN in filenames/paths
    ],
)
def test_path_tuple_from_url_parameterized(url, expected_parent_path, expected_filename):
    parent_path, filename = path_utils.path_tuple_from_url(url)
    assert (utils.p(parent_path), utils.p(filename)) == (utils.p(expected_parent_path), utils.p(expected_filename))
