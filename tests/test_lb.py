import sys
import unittest
from unittest import mock

import pytest

from xklb.fs_actions import watch as wt
from xklb.fs_extract import main as xr
from xklb.lb import lb
from xklb.tabs_extract import tabs_add

v_db = "--db", "tests/data/video.db"
xr([*v_db, "tests/data/"])

a_db = "--db", "tests/data/audio.db"
xr([*a_db, "--audio", "tests/data/"])

tabs_db = "--db", "tests/data/tabs.db"
tabs_add([*tabs_db, "https://unli.xyz/proliferation/verbs.html"])


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
    lb(["wt", *v_db, "-p", "a"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" in captured

    lb(["wt", *v_db, "-pa"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" in captured

    lb(["wt", *v_db, "-p"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" not in captured


class TestFs(unittest.TestCase):
    @mock.patch("xklb.fs_actions.play")
    def test_lb_fs(self, play_mocked):
        for SC in ["watch", "wt"]:
            lb([SC, *v_db])
            out = play_mocked.call_args[0][1].to_dict(orient="records")
            assert len(out) == 1
            assert "test.mp4" in out[0]["path"]
            assert out[0]["duration"] == 12
            assert out[0]["subtitle_count"] == 0
            assert out[0]["size"] == 135178

        sys.argv[1:] = v_db
        wt()
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert len(out) == 1
        assert "test.mp4" in out[0]["path"]
        assert out[0]["duration"] == 12
        assert out[0]["subtitle_count"] == 0
        assert out[0]["size"] == 135178

        lb(["listen", *a_db])
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert len(out) == 2
        assert "test.opus" in out[0]["path"] + out[1]["path"]

    @mock.patch("xklb.fs_actions.play")
    def test_wt_search(self, play_mocked):
        sys.argv = ["wt", *v_db, "-s", "te t", "test test", "-E", "2", "-s", "test"]
        wt()
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert out == [
            {"duration": 12, "path": "/home/xk/github/xk/lb/tests/data/test.mp4", "size": 135178, "subtitle_count": 0}
        ]

    @mock.patch("xklb.fs_actions.play")
    def test_wt_sort(self, play_mocked):
        sys.argv = ["wt", *v_db, "-u", "duration"]
        wt()
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert out == [
            {"duration": 12, "path": "/home/xk/github/xk/lb/tests/data/test.mp4", "size": 135178, "subtitle_count": 0}
        ]

    @mock.patch("xklb.fs_actions.play")
    def test_wt_size(self, play_mocked):
        sys.argv = ["wt", *v_db, "--size", "-1"]
        wt()
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert out == [
            {"duration": 12, "path": "/home/xk/github/xk/lb/tests/data/test.mp4", "size": 135178, "subtitle_count": 0}
        ]


class TestTabs(unittest.TestCase):
    @mock.patch("xklb.tabs_actions.play")
    def test_lb_tabs(self, play_mocked):
        lb(["tabs", *tabs_db])
        out = play_mocked.call_args[0][1].to_dict(orient="records")
        assert out == [
            {"frequency": "monthly", "path": "https://unli.xyz/proliferation/verbs.html", "time_valid": 2678400}
        ]
