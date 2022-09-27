import sys, unittest
from unittest import mock

import pytest

from xklb.fs_actions import watch as wt
from xklb.fs_extract import main as xr
from xklb.lb import lb

v_db = "--db", "tests/data/video.db"
xr([*v_db, "--optimize", "--scan-subtitles", "tests/data/"])

a_db = "--db", "tests/data/audio.db"
xr([*a_db, "--audio", "tests/data/"])


def test_lb_help(capsys):
    lb_help_text = "local media subcommands:,online media subcommands:".split(",")
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
    wt_help_text = "usage:,where,sort,--duration".split(",")

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
    @mock.patch("xklb.play_actions.play")
    def test_lb_fs(self, play_mocked):
        for SC in ["watch", "wt"]:
            lb([SC, *v_db])
            out = play_mocked.call_args[0][1]
            assert "test.mp4" in out["path"]
            assert out["duration"] == 12
            assert out["subtitle_count"] == 3
            assert out["size"] == 136057

        sys.argv[1:] = v_db
        wt()
        out = play_mocked.call_args[0][1]
        assert "test.mp4" in out["path"]
        assert out["duration"] == 12
        assert out["subtitle_count"] == 3
        assert out["size"] == 136057

        lb(["listen", *a_db])
        out = play_mocked.call_args[0][1]
        assert "test" in out["path"]

    @mock.patch("xklb.play_actions.play")
    def test_wt_search(self, play_mocked):
        sys.argv = [
            "wt",
            *v_db,
            "-s",
            "tests",
            "test AND data",
            "-s",
            "boom",
            "-s",
            "beep",
            "-E",
            "2",
            "-s",
            "test",
            "-E",
            "3",
        ]
        wt()
        out = play_mocked.call_args[0][1]
        assert out is not None

    @mock.patch("xklb.play_actions.play")
    def test_wt_sort(self, play_mocked):
        sys.argv = ["wt", *v_db, "-u", "duration"]
        wt()
        out = play_mocked.call_args[0][1]
        assert out is not None

    @mock.patch("xklb.play_actions.play")
    def test_wt_size(self, play_mocked):
        sys.argv = ["wt", *v_db, "--size", "-1"]  # less than 1MB
        wt()
        out = play_mocked.call_args[0][1]
        assert out is not None
