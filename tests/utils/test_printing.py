import unittest

from library.__main__ import library as lb
from library.utils import printing
from tests import utils
from tests.utils import v_db


def test_tw_print(capsys):
    for lb_command in [
        ["tw", v_db, "-p"],
        ["dl", v_db, "-p"],
        ["pl", v_db],
        ["ds", v_db],
    ]:
        lb(lb_command)
        captured = capsys.readouterr().out.replace("\n", "")
        assert "Agg" not in captured

    for lb_command in [
        ["tw", v_db, "-p", "a"],
        ["tw", v_db, "-pa"],
        ["pl", v_db, "-pa"],
        ["dl", v_db, "-p", "a"],
    ]:
        lb(lb_command)
        captured = capsys.readouterr().out.replace("\n", "")
        assert ("Agg" in captured) or ("extractor_key" in captured)


def test_col_naturaldate():
    assert printing.col_naturaldate([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert printing.col_naturaldate([{"t": 0, "t1": int(utils.ignore_tz(172799))}], "t1") == [
        {"t": 0, "t1": "Jan 02 1970"}
    ]


def test_col_naturalsize():
    assert printing.col_filesize([{"t": 0, "t1": 1}], "t") == [{"t": None, "t1": 1}]
    assert printing.col_filesize([{"t": 946684800, "t1": 1}], "t") == [{"t": "902.8 MiB", "t1": 1}]


def test_col_duration():
    assert printing.col_duration([{"t": 0, "t1": 1}], "t") == [{"t": "", "t1": 1}]
    assert printing.col_duration([{"t": 946684800, "t1": 1}], "t") == [{"t": "30 years and 7 days", "t1": 1}]


class SecondsToHHMMSSTestCase(unittest.TestCase):
    def test_positive_seconds(self):
        assert printing.seconds_to_hhmmss(1) == "    0:01"
        assert printing.seconds_to_hhmmss(59) == "    0:59"
        assert printing.seconds_to_hhmmss(600) == "   10:00"
        assert printing.seconds_to_hhmmss(3600) == " 1:00:00"
        assert printing.seconds_to_hhmmss(3665) == " 1:01:05"
        assert printing.seconds_to_hhmmss(86399) == "23:59:59"
        assert printing.seconds_to_hhmmss(86400) == "24:00:00"
        assert printing.seconds_to_hhmmss(90061) == "25:01:01"

    def test_zero_seconds(self):
        assert printing.seconds_to_hhmmss(0) == "    0:00"
