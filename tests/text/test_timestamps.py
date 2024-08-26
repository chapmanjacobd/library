from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from xklb.__main__ import library as lb


@pytest.mark.parametrize(
    "args,stdout",
    [
        (["October 2007 3pm"], "2007-10-01T15:00:00\n"),
        (["-U", "October 2007 3pm UTC"], "1191222000\n"),
        (["-U", "October 2007 3pm"], "1191222000\n"),
        (["--from-unix", "1724604514"], "2024-08-26T00:48:34\n"),
        (["-u", "-fz", "Asia/Hong_Kong", "-U", "1724597488"], "1724568688\n"),
        (["-u", "-U", "1724597488"], "1724597488\n"),
        (["-u", "-U", "1724597488", "-fz", "America/New_York"], "1724611888\n"),
        (["-u", "-U", "1724597488", "-tz", "America/New_York"], "1724583088\n"),
        (["-u", "-U", "1724597488", "-fz", "America/New_York", "-tz", "America/New_York"], "1724597488\n"),
        (["-u", "-U", "1724597488", "-fz", "America/New_York", "-tz", "America/Chicago"], "1724593888\n"),
    ],
)
@freeze_time(datetime(2015, 8, 18, 8, 51, 50, tzinfo=ZoneInfo("America/Los_Angeles")))
def test_lb_timestamps(args, stdout, capsys):
    lb(["timestamps", *args])
    captured = capsys.readouterr().out
    assert captured == stdout


@pytest.mark.parametrize(
    "args,stdout",
    [
        (["October 2007 "], "2007-10-01\n"),
        (["October 2007 ", "01/20/04"], "2007-10-01\n2004-01-20\n"),
        (["./OCTOBER 2017 - IV Issuances.pdf"], "2017-10-01\n"),
        (["-m-d-y", "01/10/05", "July 8th, 2009"], "2005-01-10\n2009-07-08\n"),
        (["-d-m-y", "01/10/05", "July 8th, 2009"], "2005-10-01\n2009-07-08\n"),
        (["-y-m-d", "01/10/05", "July 8th, 2009"], "2001-10-05\n2009-07-08\n"),
        (["-y-d-m", "01/10/05", "July 8th, 2009"], "2001-05-10\n2009-07-08\n"),
        (["-U", "October 2007 3pm UTC"], "1191196800\n"),
        (["-U", "October 2007 3pm"], "1191196800\n"),
        (["--from-unix", "1724604514"], "2024-08-26\n"),
        (["-u", "-U", "1724457600"], "1724457600\n"),
    ],
)
@freeze_time(datetime(2015, 8, 18, 8, 51, 50, tzinfo=ZoneInfo("America/Los_Angeles")))
def test_lb_dates(args, stdout, capsys):
    lb(["dates", *args])
    captured = capsys.readouterr().out
    assert captured == stdout


@pytest.mark.parametrize(
    "args,stdout",
    [
        (["October 2007 3pm"], "15:00:00\n"),
        (["-U", "October 2007 3pm UTC"], "25200\n"),
        (["-U", "October 2007 3pm"], "25200\n"),
        (["-U", "-tz", "Asia/Shanghai", "October 2007 3pm"], "54000\n"),
        (["--from-unix", "1724604514", "-tz", "Asia/Hong_Kong"], "00:48:34\n"),
        (["--from-unix", "1724604514", "-tz", "UTC"], "16:48:34\n"),
        (["-u", "-U", "1724597488"], "53488\n"),
    ],
)
@freeze_time(datetime(2015, 8, 18, 8, 51, 50, tzinfo=ZoneInfo("America/Los_Angeles")))
def test_lb_times(args, stdout, capsys):
    lb(["times", *args])
    captured = capsys.readouterr().out
    assert captured == stdout


def test_lb_dates_stdin(mock_stdin, capsys):
    with mock_stdin("October 2007\nNov. 2008"):
        lb(["dates"])
    captured = capsys.readouterr().out
    assert captured == "2007-10-01\n2008-11-01\n"
