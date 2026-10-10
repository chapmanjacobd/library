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
