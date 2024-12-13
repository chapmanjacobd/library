import pytest

from library.__main__ import library as lb


@pytest.mark.parametrize(
    ("args", "stdout"),
    [
        (
            ["--no-show-kitty", "--no-show-external", "tests/data/test.xml"],
            """## tests/data/test.xml:0

""",
        ),
    ],
)
def test_lb_plot(args, stdout, capsys):
    lb(["plot", *args])
    captured = capsys.readouterr().out
    assert all(l in captured for l in stdout)
