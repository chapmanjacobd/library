from xklb.__main__ import library as lb


def test_lb_nouns(mock_stdin, capsys):
    with mock_stdin(
        "This is a sample text with compound nouns like 'compound noun' and phrases like 'compound noun phrase'."
    ):
        lb(["nouns"])
    captured = capsys.readouterr().out
    assert (
        captured
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
