import sys, unittest
from unittest import mock

from xklb.lb import lb
from xklb.tube_actions import tube_watch
from xklb.tube_extract import tube_add, tube_update

tube_db = "--db", "tests/data/tube.db"
tube_add(
    [
        *tube_db,
        "--extra",
        "--yt-dlp-config",
        "TEST1=1 TEST2=2",
        "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm",
    ]
)


def test_tw_print(capsys):
    lb(["tw", *tube_db, "-p", "a"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" in captured

    lb(["tw", *tube_db, "-pa"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" in captured

    lb(["tw", *tube_db, "-p"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "Aggregate" not in captured


class TestTube(unittest.TestCase):
    @mock.patch("xklb.fs_actions.play")
    def test_lb_fs(self, play_mocked):
        for SC in ["tubewatch", "tw"]:
            lb([SC, *tube_db])
            out = play_mocked.call_args[0][1]
            assert "https://www.youtube.com/watch?v=QoXubRvB6tQ" in out["path"]
            assert out["duration"] == 28
            assert out["title"] == "Most Epic Video About Nothing"
            assert out["size"] == 4797012

        sys.argv[1:] = tube_db
        tube_watch()
        out = play_mocked.call_args[0][1]
        assert "https://www.youtube.com/watch?v=QoXubRvB6tQ" in out["path"]
        assert out["duration"] == 28
        assert out["title"] == "Most Epic Video About Nothing"
        assert out["size"] == 4797012

    @mock.patch("xklb.fs_actions.play")
    def test_tw_search(self, play_mocked):
        sys.argv = ["tw", *tube_db, "-s", "nothing"]
        tube_watch()
        out = play_mocked.call_args[0][1]
        assert out is not None

    @mock.patch("xklb.fs_actions.play")
    def test_tw_sort(self, play_mocked):
        sys.argv = ["tw", *tube_db, "-u", "duration"]
        tube_watch()
        out = play_mocked.call_args[0][1]
        assert out is not None

    @mock.patch("xklb.fs_actions.play")
    def test_tw_size(self, play_mocked):
        sys.argv = ["tw", *tube_db, "--size", "+1"]  # more than 1MB
        tube_watch()
        out = play_mocked.call_args[0][1]
        assert out is not None

    @mock.patch("xklb.tube_extract.process_playlist")
    def test_tubeupdate(self, play_mocked):
        tube_update([*tube_db, "--yt-dlp-config", "TEST2=4 TEST3=3"])
        out = play_mocked.call_args[0][2]
        assert out is not None
        assert play_mocked.call_args[0][2]["TEST1"] == "1"
        assert play_mocked.call_args[0][2]["TEST2"] == "4"
        assert play_mocked.call_args[0][2]["TEST3"] == "3"
