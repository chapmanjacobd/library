import pytest

from xklb.lb import library as lb


@pytest.mark.parametrize(
    "args,stdout",
    [
        (
            ["tests/data/test.xml"],
            """## tests/data/test.xml:0

| name   | type   |
|--------|--------|
| index  | int64  |
| A      | int64  |
| B      | int64  |
| C      | int64  |

""",
        ),
    ],
)
def test_lb_columns(args, stdout, capsys):
    lb(["columns", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)
