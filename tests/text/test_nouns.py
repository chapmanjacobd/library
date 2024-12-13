from library.__main__ import library as lb

simple = "This is a sample text with compound nouns like 'compound noun' and phrases like 'compound noun phrase'."


def test_lb_nouns(mock_stdin, assert_unchanged, capsys):
    with mock_stdin(simple):
        lb(["nouns"])
    captured = capsys.readouterr().out
    assert_unchanged(captured.split())


def test_lb_nouns_unique(mock_stdin, assert_unchanged, capsys):
    with mock_stdin(simple + "\n" + simple):
        lb(["nouns", "--unique"])
    captured = capsys.readouterr().out
    assert_unchanged(captured.split())


def test_lb_nouns_prepend(mock_stdin, assert_unchanged, capsys):
    with mock_stdin("log"):
        lb(["nouns", "-u", "--prepend"])
    captured = capsys.readouterr().out
    assert_unchanged(captured.split())


def test_lb_nouns_prepend_a(mock_stdin, assert_unchanged, capsys):
    with mock_stdin(simple):
        lb(["nouns", "-u", "--prepend", "a"])
    captured = capsys.readouterr().out
    assert_unchanged(captured.split())
