import shlex, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from xklb import history
from xklb.fs_extract import fs_add
from xklb.lb import library as lb
from xklb.play_actions import watch as wt
from xklb.utils import db_utils, sql_utils
from xklb.utils.log_utils import log

v_db = "tests/data/video.db"
fs_add([v_db, "--scan-subtitles", "tests/data/"])

a_db = "tests/data/audio.db"
fs_add([a_db, "--audio", "tests/data/"])


local_player_flags = [
    "-s tests -s 'test AND data' -E 2 -s test -E 3",
    "--duration-from-size=-100Mb",
    "-O",
    "-OO",
    "-OOO",
    "-OOOO",
    "-R",
    "-RR",
    "-C",
    # "-B",
    # "-B -pa",
    "-RCO",
    "--sibling",
    # "--solo",
    "-P o",
    "-P p",
    "-P t",
    # "-P s",
    "-P f",
    "-P fo",
    "-P pt",
    # "-p",
    # "-pa",
    # "-pb",
    # "-pf",
    # "-p df",
    # "-p bf",
    # "-p -P",
    # "-p --cols '*' -L inf",
    "--skip 1",
    "-s test",
    "test",
    "-s 'path : test'",
    "-w audio_count=1",
    "-w subtitle_count=1",
    "-d+0 -d-10",
    "-d=-1",
    "-S+0 -S-10",
    "-S=-1Mi",
    "-u duration",
    "--portrait",
    # "--online-media-only",
    "--local-media-only",
    "-w 'size/duration<50000'",
    "-w time_deleted=0",
    "--downloaded-within '2 days'",
    "-w 'playhead is NULL'",
    "--played-within '3 days'",
    "-w 'play_count>0'",
    "-w 'time_played>0'",
    "-w 'done>0'",
]


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
    for lb_command in [
        ["wt", v_db, "-p"],
        ["pl", v_db],
    ]:
        lb(lb_command)
        captured = capsys.readouterr().out.replace("\n", "")
        assert "Aggregate" not in captured, f"Test failed for {lb_command}"

    for lb_command in [
        ["wt", v_db, "-p", "a"],
        ["wt", v_db, "-pa"],
        ["pl", v_db, "-pa"],
    ]:
        lb(lb_command)
        captured = capsys.readouterr().out.replace("\n", "")
        assert ("Aggregate" in captured) or ("extractor_key" in captured), f"Test failed for {lb_command}"


class TestFs(unittest.TestCase):
    @mock.patch("xklb.media.media_player.single_player", return_value=SimpleNamespace(returncode=0))
    def test_lb_fs(self, play_mocked):
        for SC in ("watch", "wt"):
            lb([SC, v_db, "-w", "path like '%test.mp4'"])
            out = play_mocked.call_args[0][2]
            assert "test.mp4" in out["path"]
            assert out["duration"] == 12
            assert out["subtitle_count"] == 4
            assert out["size"] == 136057

        sys.argv = ["wt", v_db, "-w", "path like '%test.mp4'"]
        wt()
        out = play_mocked.call_args[0][2]
        assert "test.mp4" in out["path"]
        assert out["duration"] == 12
        assert out["subtitle_count"] == 4
        assert out["size"] == 136057

        lb(["listen", a_db])
        out = play_mocked.call_args[0][2]
        assert "test" in out["path"]

    @mock.patch("xklb.media.media_player.single_player", return_value=SimpleNamespace(returncode=0))
    def test_wt_sort(self, play_mocked):
        sys.argv = ["wt", v_db, "-u", "duration"]
        wt()
        out = play_mocked.call_args[0][2]
        assert out is not None

    @mock.patch("xklb.media.media_player.single_player", return_value=SimpleNamespace(returncode=0))
    def test_wt_size(self, play_mocked):
        sys.argv = ["wt", v_db, "--size", "-1"]  # less than 1MB
        wt()
        out = play_mocked.call_args[0][2]
        assert out is not None

    @mock.patch("xklb.media.media_player.single_player", return_value=SimpleNamespace(returncode=0))
    def test_undelete(self, _play_mocked):
        temp_dir = tempfile.TemporaryDirectory()

        t_db = str(Path(temp_dir.name, "test.db"))
        fs_add([t_db, "tests/data/"])
        args = SimpleNamespace(db=db_utils.connect(SimpleNamespace(database=t_db, verbose=0)))
        history.add(args, [str(Path("tests/data/test.mp4").resolve())])
        sql_utils.mark_media_deleted(args, [str(Path("tests/data/test.mp4").resolve())])
        fs_add([t_db, "tests/data/"])
        d = args.db.pop_dict("select * from media where path like '%test.mp4'")
        assert d["time_deleted"] == 0

        try:
            temp_dir.cleanup()
        except Exception as e:
            log.debug(e)


@mock.patch("xklb.play_actions.play", return_value=SimpleNamespace(returncode=0))
@pytest.mark.parametrize("flags", local_player_flags)
def test_wt_flags(play_mocked, flags):
    sys.argv = ["wt", v_db, *shlex.split(flags)]
    wt()
    out = play_mocked.call_args[0][2]
    assert out is not None, f"Test failed for {flags}"
