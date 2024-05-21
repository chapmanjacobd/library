import pytest

from xklb.lb import library as lb


@pytest.mark.parametrize(
    "args,stdout",
    [
        (
            ["--batch-size=inf", "tests/data/test.xml", "tests/data/test2.xml"],
            """## Diff tests/data/test.xml:0 and tests/data/test2.xml:0

|    |   index |   A |   B |   C | _merge     |
|----|---------|-----|-----|-----|------------|
|  0 |       0 |   1 |   3 |   5 | left_only  |
|  1 |       1 |   2 |   4 |   6 | left_only  |
|  2 |       0 |   1 |   4 |   5 | right_only |
|  3 |       1 |   2 |   4 |   3 | right_only |

""",
        ),
    ],
)
def test_lb_incremental_diff(args, stdout, capsys):
    lb(["incremental-diff", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)
