from io import StringIO

import pytest

from xklb.lb import library as lb


@pytest.fixture
def mock_stdin(monkeypatch):
    text = "This is a sample text with compound nouns like 'compound noun' and phrases like 'compound noun phrase'."
    monkeypatch.setattr("sys.stdin", StringIO(text))


def test_lb_nouns(mock_stdin, capsys):
    lb(["nouns"])
    captured = capsys.readouterr()
    assert (
        captured.out
        == """sample
text
compound
nouns
compound
noun
phrases
compound
noun
phrase
"""
    )
