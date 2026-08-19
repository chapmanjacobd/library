import tempfile
from types import SimpleNamespace

from library.__main__ import library as lb
from library.data.http_errors import HTTPStatus
from library.text import extract_text


def test_text_local_html(capsys):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temp_html:
        temp_html.write(b"<html><head><title>Real Title</title></head><body>Content</body></html>")
        temp_html.flush()

        lb(["extract-text", "--local-html", temp_html.name])

    captured = capsys.readouterr().out.replace("\n", "")
    assert captured == "Real TitleContent"


def test_get_text_skips_404_response_body(monkeypatch):
    response = SimpleNamespace(status_code=HTTPStatus.NOT_FOUND, content=b"<html><body>Error</body></html>")
    monkeypatch.setattr(extract_text.web, "session", SimpleNamespace(get=lambda *_args, **_kwargs: response))
    args = SimpleNamespace(local_html=False, selectors=[], selenium=False)

    assert list(extract_text.get_text(args, "https://example.com/missing")) == []
