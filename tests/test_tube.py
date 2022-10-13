import sys, unittest
from types import SimpleNamespace
from unittest import mock

from xklb.lb import lb
from xklb.play_actions import watch
from xklb.tube_extract import tube_add, tube_update

tube_db = "--db", "tests/data/tube.db"
tube_add(
    [
        *tube_db,
        "--extra",
        "--dl-config",
        "TEST1=1 TEST2=2",
        "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm",
    ]
)


def test_tw_print(capsys):
    for lb_command in [
        ["tw", *tube_db, "-p"],
        ["dl", *tube_db, "-p"],
        ["pl", *tube_db],
        ["ds", *tube_db],
    ]:
        lb(lb_command)
        captured = capsys.readouterr().out.replace("\n", "")
        assert "Aggregate" not in captured

    for lb_command in [
        ["tw", *tube_db, "-p", "a"],
        ["tw", *tube_db, "-pa"],
        ["pl", *tube_db, "-a"],
        ["dl", *tube_db, "-p", "a"],
    ]:
        lb(lb_command)
        captured = capsys.readouterr().out.replace("\n", "")
        assert "Aggregate" or "ie_key" in captured


class TestTube(unittest.TestCase):
    @mock.patch("xklb.player.local_player", return_value=SimpleNamespace(returncode=0))
    def test_lb_fs(self, play_mocked):
        for SC in ("tubewatch", "tw"):
            lb([SC, *tube_db])
            out = play_mocked.call_args[0][1]
            assert "https://www.youtube.com/watch?v=QoXubRvB6tQ" in out["path"]
            assert out["duration"] == 28
            assert out["title"] == "Most Epic Video About Nothing"
            assert out["size"] == 4797012

        sys.argv[1:] = tube_db
        watch()
        out = play_mocked.call_args[0][1]
        assert "https://www.youtube.com/watch?v=QoXubRvB6tQ" in out["path"]
        assert out["duration"] == 28
        assert out["title"] == "Most Epic Video About Nothing"
        assert out["size"] == 4797012

    @mock.patch("xklb.player.local_player", return_value=SimpleNamespace(returncode=0))
    def test_tw_search(self, play_mocked):
        sys.argv = ["tw", *tube_db, "-s", "nothing"]
        watch()
        out = play_mocked.call_args[0][1]
        assert out is not None

    @mock.patch("xklb.player.local_player", return_value=SimpleNamespace(returncode=0))
    def test_tw_sort(self, play_mocked):
        sys.argv = ["tw", *tube_db, "-u", "duration"]
        watch()
        out = play_mocked.call_args[0][1]
        assert out is not None

    @mock.patch("xklb.player.local_player", return_value=SimpleNamespace(returncode=0))
    def test_tw_size(self, play_mocked):
        sys.argv = ["tw", *tube_db, "--size", "+1"]  # more than 1MB
        watch()
        out = play_mocked.call_args[0][1]
        assert out is not None

    @mock.patch("xklb.tube_backend.process_playlist")
    def test_tubeupdate(self, play_mocked):
        tube_update([*tube_db, "--dl-config", "TEST2=4 TEST3=3"])
        out = play_mocked.call_args[0][2]
        assert out is not None
        assert out["TEST1"] == "1"
        assert out["TEST2"] == "4"
        assert out["TEST3"] == "3"
