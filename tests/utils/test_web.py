import pathlib
from unittest.mock import MagicMock, Mock

import pytest
from bs4 import BeautifulSoup

from library.utils import web
from library.utils.path_utils import safe_unquote
from library.utils.web import (
    WebPath,
    construct_absolute_url,
    extract_nearby_text,
    filename_from_content_disposition,
    selenium_get_page,
    url_encode,
    url_to_local_path,
)
from tests.utils import p


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
            "example.com/path/resource.txt",
        ),
    ]

    for url, expected in tests:
        result = url_to_local_path(url)
        assert p(result) == p(expected)


class MockResponse:
    def __init__(self, headers):
        self.headers = headers


@pytest.mark.parametrize(
    ("url", "output_prefix", "response_headers", "expected"),
    [
        # Content-Disposition header provides the filename
        (
            "http://example.com/path/to/resource",
            None,
            {"Content-Disposition": 'attachment; filename="downloaded_file.txt"'},
            "example.com/path/to/downloaded_file.txt",
        ),
        (
            "http://example.com/path/to/resource/",
            None,
            {"Content-Disposition": 'attachment; filename="downloaded_file.txt"'},
            "example.com/path/to/resource/downloaded_file.txt",
        ),
        # No Content-Disposition, filename derived from URL
        ("http://example.com/path/to/resource.html", None, {}, "example.com/path/to/resource.html"),
        ("http://example.com/t/test.txt", "", {}, "example.com/t/test.txt"),
        # output_prefix provided, appended to generated output path
        ("http://example.com/some/resource", "/prefix/path", {}, "/prefix/path/example.com/some/resource"),
        # Illegal characters in filename from Content-Disposition are replaced
        (
            "http://example.com/test/",
            None,
            {"Content-Disposition": 'attachment; filename="../../me.txt"'},
            "example.com/test/me.txt",
        ),
        (
            "http://example.com/test/",
            None,
            {"Content-Disposition": 'attachment; filename="./%2F..%2F..%2F..%2F../../me.txt"'},
            "example.com/test/me.txt",
        ),
        (
            "http://example.com",
            None,
            {"Content-Disposition": 'attachment; filename="na/me.txt"'},
            "example.com/na/me.txt",
        ),
        (
            "http://example.com/no-name.txt",
            None,
            {"Content-Disposition": "attachment"},
            "example.com/no-name.txt",
        ),
        (
            "http://example.com/no-name.txt",
            None,
            {"Content-Disposition": 'attachment; filename=""'},
            "example.com/no-name.txt",
        ),
        (
            "http://example.com/test/get",
            None,
            {
                "Content-Disposition": 'Content-Disposition: form-data; name="file"; filename="你好.xlsx"; filename*=UTF-8'
                "%E4%BD%A0%E5%A5%BD.xlsx"
            },
            "example.com/test/你好.xlsx",
        ),
    ],
)
def test_url_to_local_path_with_response(url, output_prefix, response_headers, expected):
    response = MockResponse(response_headers)
    result = url_to_local_path(url, response, output_prefix)
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

    root_path = WebPath("/")
    assert isinstance(root_path, pathlib.Path)

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


@pytest.mark.parametrize(
    ("base_url", "href", "expected"),
    [
        ("https://unli.xyz/diskprices/index.html", "./ch/", "https://unli.xyz/diskprices/ch/"),
        ("https://unli.xyz/diskprices/index.html", "ch/", "https://unli.xyz/diskprices/ch/"),
        ("https://unli.xyz/diskprices/index.html", "/ch/", "https://unli.xyz/ch/"),
        ("https://unli.xyz/diskprices/", "ch/", "https://unli.xyz/diskprices/ch/"),
        ("https://unli.xyz/diskprices/", "/ch/", "https://unli.xyz/ch/"),
        ("https://unli.xyz/diskprices", "ch/", "https://unli.xyz/ch/"),
        ("https://unli.xyz/diskprices", "/ch/", "https://unli.xyz/ch/"),
        ("https://unli.xyz/", "ch/", "https://unli.xyz/ch/"),
        ("https://unli.xyz", "/ch/", "https://unli.xyz/ch/"),
        ("https://unli.xyz", "diskprices/ch/", "https://unli.xyz/diskprices/ch/"),
        ("https://unli.xyz/", "//example.com/ch/", "https://example.com/ch/"),
        ("https://unli.xyz/diskprices", "ftp://example.com/ch/", "ftp://example.com/ch/"),
        ("https://unli.xyz/diskprices", "ssh://example.com/ch/", "ssh://example.com/ch/"),
        ("https://example.com/", "?q=url+query+string", "https://example.com/?q=url+query+string"),
        ("https://example.com/", "#absolute-urls", "https://example.com/#absolute-urls"),
        ("https://archive.org/download/test/", "test1.pdf", "https://archive.org/download/test/test1.pdf"),
        (
            "https://archive.org/download/test",
            "test1.pdf",
            "https://archive.org/download/test1.pdf",
        ),  # broken, not RFC 3986 compliant
    ],
)
def test_construct_absolute_url(base_url, href, expected):
    result = construct_absolute_url(base_url, href)
    assert result == expected


@pytest.mark.parametrize(
    ("parent_url", "child_url", "expected"),
    [
        ("http://example.com", "http://example.com", False),
        ("http://example.com/", "http://example.com", False),
        ("http://example.com", "http://example.com/anypath", True),
        ("http://example.com/", "http://example.com/anypath", True),
        ("http://example.com/a", "http://example.com/a/b", True),
        ("http://example.com/a", "http://example.com/other/b", True),
        ("http://example.com/a/", "http://example.com/a/b", True),
        ("http://example.com/a/b.html", "http://example.com/a/b/c", True),
        ("http://example.com/a/b.html", "http://example.com/a/other/c", True),
        ("http://example.com/a/b", "http://example.com/a/b/c", True),
        ("http://example.com/a/b", "http://example.com/a/other/c", True),
        ("http://example.com/a/b/", "http://example.com/a/b/c", True),
        ("http://example.com/a/b/", "http://example.com/a/other/c", False),
        ("http://example.com/fcdex.htm", "http://example.com/ff1300/fc01277.htm", True),
        ("http://example.com/ff1300", "http://example.com/ff1300/fc01277.htm", True),
        ("http://example.com/ff1300/", "http://example.com/ff1300/fc01277.htm", True),
        ("http://example.com/ff1300/", "http://example.com/ff1301/fc01277.htm", False),
    ],
)
def test_is_subpath(parent_url, child_url, expected):
    result = web.is_subpath(parent_url, child_url)
    assert result is expected


@pytest.mark.parametrize(
    ("content_disposition", "expected_filename"),
    [
        ("", None),
        ("attachment; filename=test.txt", "test.txt"),
        ('attachment; filename="test.txt"', "test.txt"),
        ("attachment; filename=test.txt;", "test.txt"),
        ('attachment; filename="test with spaces.txt"', "test with spaces.txt"),
        ('attachment; filename="test\\"with\\"quotes.txt"', 'test"with"quotes.txt'),
        ("attachment; filename*=UTF-8''test%C3%A4.txt", "testä.txt"),
        ("attachment; filename=test.pdf; filename*=utf-8''test%C3%A4.txt", "testä.txt"),
        ("attachment; filename=test.pdf; other=stuff", "test.pdf"),
        ("inline; filename=image.jpg", "image.jpg"),
    ],
)
def test_filename_from_content_disposition(content_disposition, expected_filename):
    mock_response = Mock()
    mock_response.headers = {"Content-Disposition": content_disposition}
    assert filename_from_content_disposition(mock_response) == expected_filename


def test_selenium_get_page_without_cookies():
    mock_driver = MagicMock()
    args = MagicMock(driver=mock_driver, cookies=None, cookies_from_browser=None)
    url = "https://www.example.com/path/to/page"
    selenium_get_page(args, url)
    mock_driver.get.assert_called_once_with(url)


def test_parse_cookies_from_browser():
    assert web.parse_cookies_from_browser("chrome") == ("chrome", None, None, None)
    assert web.parse_cookies_from_browser("firefox+gnomekeyring") == ("firefox", None, "GNOMEKEYRING", None)
    assert web.parse_cookies_from_browser("chrome:profile") == ("chrome", "profile", None, None)
    assert web.parse_cookies_from_browser("brave::container") == ("brave", None, None, "container")
    assert web.parse_cookies_from_browser("chromium+basictext:profile::container") == (
        "chromium",
        "profile",
        "BASICTEXT",
        "container",
    )

    with pytest.raises(ValueError, match="unsupported browser"):
        web.parse_cookies_from_browser("invalid_browser")

    with pytest.raises(ValueError, match="unsupported keyring"):
        web.parse_cookies_from_browser("chrome+invalid_keyring")


def test_is_index():
    assert web.is_index("http://example.com/")
    assert web.is_index("http://example.com/dir/")
    assert web.is_index("http://example.com/index.html")
    assert web.is_index("http://example.com/index.php")
    assert web.is_index("http://example.com/index.php?dir=somedir")
    assert not web.is_index("http://example.com/file.txt")
    assert not web.is_index("http://example.com/image.jpg")


def test_remove_apache_sorting_params():
    url = "http://example.com/?C=N&O=D"
    expected = "http://example.com/"
    assert web.remove_apache_sorting_params(url) == expected

    url = "http://example.com/?C=M&O=A&other=param"
    expected = "http://example.com/?other=param"
    assert web.remove_apache_sorting_params(url) == expected

    url = "http://example.com/dir/?C=S;O=A"
    expected = "http://example.com/dir/"
    assert web.remove_apache_sorting_params(url) == expected


def test_fake_title():
    url = "https://www.example.com/path/to/page?query=string#fragment"
    expected = "example.com  path to page  query=string: fragment"
    assert web.fake_title(url) == expected

    url = "http://example.com"
    expected = "example.com   :"
    assert web.fake_title(url) == expected


def mock_requests_session_head(url, timeout=None):
    mock_response = Mock()
    if url.endswith(".html"):
        mock_response.headers = {"Content-Type": "text/html"}
    elif url.endswith(".xml"):
        mock_response.headers = {"Content-Type": "application/xml"}
    elif url.endswith(".txt"):
        mock_response.headers = {"Content-Type": "text/plain"}
    elif url.endswith(".jpg"):
        mock_response.headers = {"Content-Type": "image/jpeg"}
    else:
        mock_response.headers = {}
    return mock_response


def test_is_html():
    args = Mock()
    args.sleep_interval_requests = 0

    # We need to mock requests_session
    original_session = web.requests_session
    web.requests_session = Mock(return_value=Mock(head=mock_requests_session_head))

    try:
        assert web.is_html(args, "http://example.com/page.html")
        # .xml extension is in media_extensions, so it returns False immediately.
        # To test content-type check for xml, use a URL without extension.
        # We need to update mock_requests_session_head to handle this case if we want to test it.
        # For now, let's just assert that .xml returns False due to extension check.
        assert not web.is_html(args, "http://example.com/data.xml")

        assert not web.is_html(args, "http://example.com/image.jpg")
        assert not web.is_html(args, "http://example.com/text.txt")
        # fast path extension check
        assert not web.is_html(args, "http://example.com/video.mp4")
    finally:
        web.requests_session = original_session
