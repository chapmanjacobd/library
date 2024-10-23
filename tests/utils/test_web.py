import pathlib

import pytest
from bs4 import BeautifulSoup

from tests.utils import p
from xklb.utils.web import WebPath, extract_nearby_text, safe_unquote, url_encode, url_to_local_path


def test_url_to_local_path():
    tests = [
        ("http://example.com/path/to/resource.html", "example.com/path/to/resource.html"),
        ("https://another-example.com/a/b/c/d/e/f/g.txt", "another-example.com/a/b/c/d/e/f/g.txt"),
        ("http://example.com/space%20in%20path/to/resource.html", "example.com/space in path/to/resource.html"),
        (
            "https://another-example.com/path/to/special%20characters%21%40%23.txt",
            "another-example.com/path/to/special characters@23.txt",
        ),
        (
            "http://example.com/interesting%2Fpath%2Fwith%2Fslashes/resource.txt",
            "example.com/interesting/path/with/slashes/resource.txt",
        ),
        (
            "http://example.com/interesting%2F..%2F..%2F..%2F../../path/resource.txt",
            "example.com/interesting/_/_/_/_/_/path/resource.txt",
        ),
    ]

    for url, expected in tests:
        result = url_to_local_path(url)
        assert p(result) == p(expected)


class MockResponse:
    def __init__(self, headers):
        self.headers = headers


@pytest.mark.parametrize(
    ("url", "output_path", "output_prefix", "response_headers", "expected"),
    [
        # Content-Disposition header provides the filename
        (
            "http://example.com/path/to/resource",
            None,
            None,
            {"Content-Disposition": 'attachment; filename="downloaded_file.txt"'},
            "example.com/path/to/downloaded_file.txt",
        ),
        (
            "http://example.com/path/to/resource/",
            None,
            None,
            {"Content-Disposition": 'attachment; filename="downloaded_file.txt"'},
            "example.com/path/to/resource/downloaded_file.txt",
        ),
        # No Content-Disposition, filename derived from URL
        ("http://example.com/path/to/resource.html", None, None, {}, "example.com/path/to/resource.html"),
        # output_path provided, other parameters ignored except for output prefix
        ("http://example.com/t/test.txt", "custom/path/custom_file.txt", None, {}, "custom/path/custom_file.txt"),
        ("http://example.com/t/test.txt", "custom/path/custom_file.txt", "", {}, "custom/path/custom_file.txt"),
        (
            "http://example.com/t/test.txt",
            "/custom/path/custom_file.txt",
            "dir/dir2/",
            {},
            "/custom/path/custom_file.txt",
        ),
        (
            "http://example.com/t/test.txt",
            "custom/path/custom_file.txt",
            "dir/dir2/",
            {},
            "dir/dir2/custom/path/custom_file.txt",
        ),
        # output_prefix provided, appended to generated output path
        ("http://example.com/some/resource", None, "/prefix/path", {}, "/prefix/path/example.com/some/resource"),
        # Illegal characters in filename from Content-Disposition are replaced
        (
            "http://example.com/test/",
            None,
            None,
            {"Content-Disposition": 'attachment; filename="../../me.txt"'},
            "example.com/test/_/_/me.txt",
        ),
        (
            "http://example.com",
            None,
            None,
            {"Content-Disposition": 'attachment; filename="na/me.txt"'},
            "example.com/na/me.txt",
        ),
        (
            "http://example.com/no-name.txt",
            None,
            None,
            {"Content-Disposition": "attachment"},
            "example.com/no-name.txt",
        ),
        (
            "http://example.com/no-name.txt",
            None,
            None,
            {"Content-Disposition": 'attachment; filename=""'},
            "example.com/no-name.txt",
        ),
        (
            "http://example.com/test/",
            None,
            None,
            {
                "Content-Disposition": 'Content-Disposition: form-data; name="file"; filename="你好.xlsx"; filename*=UTF-8'
                "%E4%BD%A0%E5%A5%BD.xlsx"
            },
            "example.com/test/你好.xlsx",
        ),
    ],
)
def test_url_to_local_path_with_response(url, output_path, output_prefix, response_headers, expected):
    response = MockResponse(response_headers)
    result = url_to_local_path(url, response, output_path, output_prefix)
    assert p(result) == p(expected), f"Failed for URL: {url}"


unquote_results = [
    (
        "http://example.com/some%20path;param%3Dvalue?query=value%23with%23hashes#fragment%2Fpart",
        "http://example.com/some path;param=value?query=value%23with%23hashes#fragment/part",
    ),
    ("http://example.com/some%20path", "http://example.com/some path"),
    (
        "http://example.com/test?query%3Dvalue%26=another%3Dtest",
        "http://example.com/test?query%3Dvalue%26=another%3Dtest",
    ),
    ("http://example.com/test?query=value&another=test", "http://example.com/test?query=value&another=test"),
    ("http://example.com/test#fragment%2Fpart", "http://example.com/test#fragment/part"),
    ("http://example.com/?q=a%26b", "http://example.com/?q=a%26b"),
    (
        "http://example.com/path%2Fto%2Fresource?search=foo%20bar%26baz%3Dqux#sec%2Ftion",
        "http://example.com/path/to/resource?search=foo bar%26baz%3Dqux#sec/tion",
    ),
    (
        "https://example.com/products?name=Widget%20Pro&details=color%3DBlue%26size%3DLarge&discount_code=SPRING20",
        "https://example.com/products?name=Widget Pro&details=color%3DBlue%26size%3DLarge&discount_code=SPRING20",
    ),
]


@pytest.mark.parametrize(("test_input", "expected"), unquote_results)
def test_safe_unquote(test_input, expected):
    assert safe_unquote(test_input) == expected


quote_results = [
    (
        "http://example.com/some path",
        "http://example.com/some%20path",
    ),
    (
        "http://example.com/test?query%3Dvalue%26=another%3Dtest",
        "http://example.com/test?query%3Dvalue%26=another%3Dtest",
    ),
    (
        "http://example.com/test?query=value&another=test",
        "http://example.com/test?query=value&another=test",
    ),
    (
        "http://example.com/?q=a%26b",
        "http://example.com/?q=a%26b",
    ),
    (
        "http://example.com/path/to/resource?search=foo bar%26baz%3Dqux",
        "http://example.com/path/to/resource?search=foo%20bar%26baz%3Dqux",
    ),
    (
        "http://example.com/some path;param=value?query=value%23with%23hashes#fragment/part",
        "http://example.com/some%20path;param%3Dvalue?query=value%23with%23hashes#fragment/part",
    ),
    (
        "https://example.com/products?name=Widget Pro&details=color%3DBlue%26size%3DLarge&discount_code=SPRING20",
        "https://example.com/products?name=Widget%20Pro&details=color%3DBlue%26size%3DLarge&discount_code=SPRING20",
    ),
]


@pytest.mark.parametrize(("test_input", "expected"), quote_results)
def test_safe_quote(test_input, expected):
    assert url_encode(test_input) == expected


html = """
<html>
  <body>
    <a href="link1">Text 1</a>
    Some text between the links.
    <a href="link2">Text 2</a>
    <a href="link3">Text 3</a>
  </body>
</html>
"""

soup = BeautifulSoup(html, "lxml")


def test_extract_nearby_text():
    before, after = extract_nearby_text(soup.find("a", href="link1"), "a")
    assert (before, after) == ("", "Some text between the links.")

    before, after = extract_nearby_text(soup.find("a", href="link2"), "a")
    assert (before, after) == ("Some text between the links.", "")

    before, after = extract_nearby_text(soup.find("a", href="link3"), "a")
    assert (before, after) == ("", "")


def test_extract_nearby_text2():
    html = """
    <ul class="dotul twocolul"><li><a href="https://fourble.co.uk/podcast/systemau">#systemau</a> - Archive of the Australian Linux-leaning tech podcast</li><li><a href="https://fourble.co.uk/podcast/24cast">24cast</a>
    """

    soup = BeautifulSoup(html, "lxml")

    before, after = extract_nearby_text(soup.find("a", href="https://fourble.co.uk/podcast/systemau"), "a")
    assert (before, after) == ("", "- Archive of the Australian Linux-leaning tech podcast")


def test_parent_property():
    local_path = WebPath("some/local/path")
    assert isinstance(local_path, pathlib.Path)
    assert str(local_path.parent) == "some/local"

    root_path = WebPath("/")
    assert isinstance(root_path, pathlib.Path)
    assert str(root_path.parent) == "/"

    web_path = WebPath("http://example.com/some/path")
    assert isinstance(web_path, WebPath)
    assert str(web_path.parent) == "http://example.com/some"

    web_path = WebPath("http://example.com/some/")
    assert isinstance(web_path, WebPath)
    assert str(web_path.parent) == "http://example.com"

    web_path = WebPath("https://<netloc>/<path1>/<path2>;<params>?<query1>&<query2>#<fragment1>&<fragment2>")
    assert isinstance(web_path, WebPath)
    assert str(web_path.parent) == "https://<netloc>/<path1>/<path2>;<params>?<query1>&<query2>#<fragment1>"
    assert str(web_path.parent.parent) == "https://<netloc>/<path1>/<path2>;<params>?<query1>&<query2>"
    assert str(web_path.parent.parent.parent) == "https://<netloc>/<path1>/<path2>;<params>?<query1>"
    assert str(web_path.parent.parent.parent.parent) == "https://<netloc>/<path1>/<path2>;<params>"
    assert str(web_path.parent.parent.parent.parent.parent) == "https://<netloc>/<path1>/<path2>"
    assert str(web_path.parent.parent.parent.parent.parent.parent) == "https://<netloc>/<path1>"
    assert str(web_path.parent.parent.parent.parent.parent.parent.parent) == "https://<netloc>"
    assert str(web_path.parent.parent.parent.parent.parent.parent.parent.parent) == "https://<netloc>"
