from library import usage
from library.document import document_convert
from library.text import convert


def test_text_convert_parser_uses_document_converter(monkeypatch):
    monkeypatch.setattr(document_convert, "build_parser", lambda usage_text: usage_text)

    assert convert.parse_args() == usage.document_convert
