import shlex

import pytest

from library.__main__ import library as lb


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ("-s t%s 1", "t1"),
        ("-s t%s \n1\n", "t1"),
        ("-s t%s \"'1'\"", "t1"),
        ("-s t%s '\"1\"'", "t1"),
        ('-s t%s "1 [20]"', "t1 20"),
        ('-s t%s "1 (20)"', "t1 20"),
        ("-s t%s 1 2 3", "t1\nt2\nt3"),
    ],
)
def test_main(capsys, argv, expected):
    lb(["expand-links", *shlex.split(argv)])
    assert capsys.readouterr().out.strip() == expected.replace(" ", "%20")
