import json

import pytest

from xklb.__main__ import library as lb

simple = '{"A": 1, "B": 3, "C": 5}\n{"A": 2, "B": 4, "C": 6}'


@pytest.mark.parametrize(
    ('args', 'stdout'),
    [
        (
            ["tests/data/test.xml"],
            """## tests/data/test.xml:0

|   index |   A |   B |   C |
|---------|-----|-----|-----|
|       0 |   1 |   3 |   5 |
|       1 |   2 |   4 |   6 |
""",
        ),
    ],
)
def test_lb_markdown_tables(args, stdout, capsys):
    lb(["markdown-tables", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)


def test_lb_markdown_tables_json(mock_stdin, assert_unchanged, capsys):
    with mock_stdin(simple):
        lb(["markdown-tables", "--from-json", "--to-json"])
    captured = capsys.readouterr().out
    assert_unchanged([json.loads(s) for s in captured.splitlines()])


def test_lb_markdown_tables_transpose(mock_stdin, assert_unchanged, capsys):
    with mock_stdin(simple):
        lb(["markdown-tables", "--from-json", "--transpose", "--to-json"])
    captured = capsys.readouterr().out
    assert_unchanged([json.loads(s) for s in captured.splitlines()])
