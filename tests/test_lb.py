import sys
import tempfile
import unittest
from unittest import mock

import pytest

from xklb.fs_actions import watch as wt
from xklb.fs_extract import main as xr
from xklb.lb import lb

db = "--db", "tests/data/test.db"

xr([*db, "tests/data/"])


def test_lb_help(capsys):
    lb_help_text = "usage:,extract,xr,subtitle,sub,listen,lt,watch,wt,filesystem,fs,tubelist,playlist,playlists,tubeadd,ta,tubeupdate,tu,tubewatch,tw,entries,tubelisten,tl".split(
        ","
    )
    lb()
    captured = capsys.readouterr().out
    for help_text in lb_help_text:
        assert help_text in captured

    lb(["-h"])
    captured = capsys.readouterr().out
    for help_text in lb_help_text:
        assert help_text in captured


def test_wt_help(capsys):
    wt_help_text = "usage:,WHERE,SORT,--duration".split(",")

    sys.argv[1:] = ["-h"]
    with pytest.raises(SystemExit):
        wt()
    captured = capsys.readouterr().out.replace("\n", "")
    for help_text in wt_help_text:
        assert help_text in captured

    with pytest.raises(SystemExit):
        lb(["wt", "-h"])
    captured = capsys.readouterr().out.replace("\n", "")
    for help_text in wt_help_text:
        assert help_text in captured


def test_wt_print(capsys):
    with pytest.raises(SystemExit):
        lb(["wt", *db, "-p", "a"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" in captured

    with pytest.raises(SystemExit):
        lb(["wt", *db, "-pa"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" in captured

    with pytest.raises(SystemExit):
        lb(["wt", *db, "-p"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" not in captured
    # assert "tests/data/test.mp4" in captured


class TestLB(unittest.TestCase):
    @mock.patch("xklb.fs_actions.play")
    def test_lb_fs(self, play_mocked):
        for subcommand in ["watch", "wt"]:
            lb([subcommand, *db])
            out = play_mocked.call_args[0][1].to_dict(orient="records")
            assert out == [
                {
                    "path": "/home/xk/github/xk/lb/tests/data/test.mp4",
                    "duration": 12,
                    "subtitle_count": 0,
                    "size": 135178,
                }
            ]

        sys.argv[1:] = db
        wt()
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert out == [
            {"path": "/home/xk/github/xk/lb/tests/data/test.mp4", "duration": 12, "subtitle_count": 0, "size": 135178}
        ]

        lb(["listen", *db])
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert out == [{"path": "/home/xk/github/xk/lb/tests/data/test.mp4", "duration": 12, "size": 135178}]

    # @mock.patch("xklb.fs_actions.play")
    # def test_wt_sort(self, play_mocked):

    # @mock.patch("xklb.fs_actions.play")
    # def test_wt_size(self, play_mocked):

    # @mock.patch("xklb.fs_actions.play")
    # def test_wt_duration(self, play_mocked):

    # @mock.patch("xklb.fs_actions.play")
    # def test_wt_search(self, play_mocked):
    #     sys.argv = ["wt", "-s", "test,test1 test2", "test3", "-E", "test4", "-s", "test5"]
    #     wt()
