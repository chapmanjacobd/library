from bs4 import BeautifulSoup

from xklb.utils.web import extract_nearby_text

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
