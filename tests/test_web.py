import pytest
from bs4 import BeautifulSoup

from xklb.utils.web import extract_nearby_text, safe_unquote


@pytest.mark.parametrize(
    "test_input,expected",
    [
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
    ],
)
def test_safe_unquote(test_input, expected):
    assert safe_unquote(test_input) == expected


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

soup = BeautifulSoup(html, "html.parser")


def test_extract_nearby_text():
    before, after = extract_nearby_text(soup.find("a", href="link1"))
    assert (before, after) == ("", "Some text between the links.")

    before, after = extract_nearby_text(soup.find("a", href="link2"))
    assert (before, after) == ("Some text between the links.", "")

    before, after = extract_nearby_text(soup.find("a", href="link3"))
    assert (before, after) == ("", "")


def test_extract_nearby_text2():
    html = """
    <ul class="dotul twocolul"><li><a href="https://fourble.co.uk/podcast/systemau">#systemau</a> - Archive of the Australian Linux-leaning tech podcast</li><li><a href="https://fourble.co.uk/podcast/24cast">24cast</a>
    """

    soup = BeautifulSoup(html, "html.parser")

    before, after = extract_nearby_text(soup.find("a", href="https://fourble.co.uk/podcast/systemau"))
    assert (before, after) == ("", "- Archive of the Australian Linux-leaning tech podcast")
