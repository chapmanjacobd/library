import sys
import tempfile
import unittest
from unittest import mock

import pytest

from xklb.fs_actions import watch as wt
from xklb.fs_extract import main as xr
from xklb.lb import lb

v_db = "--db", "tests/data/video.db"
a_db = "--db", "tests/data/audio.db"

xr([*v_db, "tests/data/"])
xr([*a_db, "--audio", "tests/data/"])


def test_lb_help(capsys):
    lb_help_text = "usage:,extract,xr,listen,lt,watch,wt,filesystem,fs,tubelist,playlist,playlists,tubeadd,ta,tubeupdate,tu,tubewatch,tw,tubelisten,tl".split(
        ","
    )
    sys.argv = ["lb"]
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

    sys.argv = ["wt", "-h"]
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
        lb(["wt", *v_db, "-p", "a"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" in captured

    with pytest.raises(SystemExit):
        lb(["wt", *v_db, "-pa"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" in captured

    with pytest.raises(SystemExit):
        lb(["wt", *v_db, "-p"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" not in captured


class TestLB(unittest.TestCase):
    @mock.patch("xklb.fs_actions.play")
    def test_lb_fs(self, play_mocked):
        for subcommand in ["watch", "wt"]:
            lb([subcommand, *v_db])
            out = play_mocked.call_args[0][1].to_dict(orient="records")
            assert len(out) == 1
            assert "tests/data/test.mp4" in out[0]["path"]
            assert out[0]["duration"] == 12
            assert out[0]["subtitle_count"] == 0
            assert out[0]["size"] == 135178

        sys.argv[1:] = v_db
        wt()
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert len(out) == 1
        assert "tests/data/test.mp4" in out[0]["path"]
        assert out[0]["duration"] == 12
        assert out[0]["subtitle_count"] == 0
        assert out[0]["size"] == 135178

        lb(["listen", *a_db])
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert len(out) == 2
        assert "tests/data/test.opus" in out[0]["path"] + out[1]["path"]

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
