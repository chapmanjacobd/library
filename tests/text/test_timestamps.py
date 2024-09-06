import pytest

from xklb.__main__ import library as lb


@pytest.mark.parametrize("p", [["1970-01-01 00:00:01"], ["--from-unix", "1"]])
@pytest.mark.parametrize("fz", [["-fz", "America/New_York"], ["-fz", "America/Chicago"]])
@pytest.mark.parametrize("tz", [["-tz", "America/New_York"], ["-tz", "America/Chicago"]])
@pytest.mark.parametrize("s", [[], ["-d"], ["-t"]])
@pytest.mark.parametrize("f", [[], ["-TZ"]])
def test_lb_timestamps_tz(assert_unchanged, p, fz, tz, s, f, capsys):
    lb(["timestamps", *p, *fz, *tz, *s, *f])
    captured = capsys.readouterr().out.strip()
    assert_unchanged(captured)


@pytest.mark.parametrize("p", [["--from-unix", "1"]])
@pytest.mark.parametrize("fz", [[], ["-fz", "America/Chicago"]])
@pytest.mark.parametrize("s", [[], ["-d"], ["-t"]])
@pytest.mark.parametrize("f", [["-U"]])
def test_lb_timestamps_tz_unix(assert_unchanged, p, fz, s, f, capsys):
    lb(["timestamps", *p, *fz, *s, *f])
    captured = capsys.readouterr().out.strip()
    assert_unchanged(captured)


@pytest.mark.parametrize(
    ("args", "stdout"),
    [
        (["October 2007 "], "2007-10-01\n"),
        (["October 2007 ", "01/20/04"], "2007-10-01\n2004-01-20\n"),
        (["./OCTOBER 2017 - IV Issuances.pdf"], "2017-10-01\n"),
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
