import pytest

from xklb.lb import library as lb


@pytest.mark.parametrize(
    "args,stdout",
    [
        (["October 2007 "], "2007-10-01\n"),
        (["October 2007 ", "01/20/04"], "2007-10-01\n2004-01-20\n"),
        (["./OCTOBER 2017 - IV Issuances.pdf"], "2017-10-01\n"),
        (["--timestamp", "October 2007 3pm"], "2007-10-01T15:00:00\n"),
        (["--time-only", "October 2007 3pm"], "15:00:00\n"),
        (["-m-d-y", "01/10/05", "July 8th, 2009"], "2005-01-10\n2009-07-08\n"),
        (["-d-m-y", "01/10/05", "July 8th, 2009"], "2005-10-01\n2009-07-08\n"),
        (["-y-m-d", "01/10/05", "July 8th, 2009"], "2001-10-05\n2009-07-08\n"),
        (["-y-d-m", "01/10/05", "July 8th, 2009"], "2001-05-10\n2009-07-08\n"),
    ],
)
def test_lb_dates(args, stdout, capsys):
    lb(["dates", *args])
    captured = capsys.readouterr().out
    assert captured == stdout


def test_lb_dates_stdin(mock_stdin, capsys):
    with mock_stdin("October 2007\nNov. 2008"):
        lb(["dates"])
    captured = capsys.readouterr().out
    assert captured == "2007-10-01\n2008-11-01\n"
