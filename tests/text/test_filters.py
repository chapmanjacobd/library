import io

from library.__main__ import library as lb
from library.text.filters import clean_text


def test_border_supports_multiline_text(capsys):
    lb(["text", "border", "--char", "=", "--padding", "1", "hello", "world"])

    assert capsys.readouterr().out == "===============\n= hello world =\n===============\n"


def test_border_reads_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("piped text\n"))

    lb(["text", "border"])

    assert "piped text" in capsys.readouterr().out


def test_clean_text_joins_wrapped_lines_and_preserves_lists():
    text = "┃ first   line\nsecond line\n\n\n\n- item one\n  item two\n"

    assert clean_text(text, "┃|", min_blank_lines=3) == "first line second line\n\n- item one item two"
