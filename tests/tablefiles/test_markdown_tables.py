import pytest

from xklb.lb import library as lb


@pytest.mark.parametrize(
    "args,stdout",
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
