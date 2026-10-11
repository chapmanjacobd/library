import tempfile

from library.__main__ import library as lb


def test_links_local_html_none(capsys):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temp_html:
        temp_html.write(b"<html><head><title>Real Title</title></head><body>Content</body></html>")
        temp_html.flush()

        lb(["extract-links", "--local-html", temp_html.name])

    captured = capsys.readouterr().out.replace("\n", "")
    assert captured == ""


def test_links_local_html(capsys):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temp_html:
        temp_html.write(
            b"""<meta http-equiv="content-type" content="text/html; charset=utf-8"><li>s, flour, and salt.</li>
<li><i><a href="https://en.wikipedia.org/w/index.php?title=Tortang_kamote&amp;action=edit&amp;redlink=1" class="new" title="Tortang kamote (page does not exist)">Tortang kamote</a></i> - an omelette made with mashed sweet potato, eggs, flour, and salt.</li>"""
        )
        temp_html.flush()

        lb(["extract-links", "--local-html", temp_html.name])

    captured = capsys.readouterr().out.replace("\n", "")
    assert captured == "https://en.wikipedia.org/w/index.php?title=Tortang_kamote&action=edit&redlink=1"


def test_links_local_html_excludes_tracking_urls(capsys):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temp_html:
        temp_html.write(
            b"""<a href="https://www.googletagmanager.com/gtag/js">Google tag manager</a>
<a href="https://www.google-analytics.com/g/collect?v=2">Google Analytics</a>
<link href="https://fonts.googleapis.com/css2?family=Roboto" rel="stylesheet">
<link href="https://fonts.gstatic.com/s/roboto/v30/foo.woff2" rel="preload">
<a href="https://example.com/document.pdf">Document</a>"""
        )
        temp_html.flush()

        lb(["extract-links", "--local-html", temp_html.name])

    captured = capsys.readouterr().out.replace("\n", "")
    assert captured == "https://example.com/document.pdf"


def test_extract_links_recursive(crawl_server, capsys):
    lb(["extract-links", "-R", crawl_server, "--path-exclude", "*/tag/*"])

    out = set(capsys.readouterr().out.split())
    assert f"{crawl_server}a.html" in out
    assert f"{crawl_server}sub/b.html" in out
    assert f"{crawl_server}sub/c.html" in out
    assert f"{crawl_server}img.png" in out
    assert "https://external.example.com/x" in out
    assert f"{crawl_server}tag/deep.html" not in out


def test_extract_links_recursive_only_spiders_within_parent(crawl_server, capsys):
    # a link to a page in a sibling directory is downloaded but not followed
    lb(["extract-links", "-R", f"{crawl_server}sub/b.html", "--path-exclude", "*/tag/*"])

    out = set(capsys.readouterr().out.split())
    assert f"{crawl_server}a.html" in out  # yielded (downloaded) from sub/b.html
    assert f"{crawl_server}sub/c.html" in out  # within parent, followed
    assert f"{crawl_server}index.html" not in out  # sibling of the seed parent is not followed


def test_extract_links_not_recursive_is_single_page(crawl_server, capsys):
    lb(["extract-links", crawl_server])

    out = set(capsys.readouterr().out.split())
    assert f"{crawl_server}a.html" in out
    assert f"{crawl_server}sub/b.html" not in out


def test_extract_links_glob_include(crawl_server, capsys):
    lb(["extract-links", crawl_server, "--path-include", "*/a.html"])

    out = capsys.readouterr().out.split()
    assert out == [f"{crawl_server}a.html"]
