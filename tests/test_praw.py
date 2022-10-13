import sys, unittest
from argparse import Namespace
from types import SimpleNamespace
from unittest import mock

from xklb.db import connect
from xklb.lb import lb
from xklb.play_actions import watch
from xklb.praw_extract import reddit_add, reddit_update

reddit_db = "--db", "tests/data/reddit.db"
reddit_add([*reddit_db, "--limit", "10", "https://old.reddit.com/user/BuonaparteII/"])
reddit_add([*reddit_db, "--limit", "1", "https://old.reddit.com/r/pytest/"])


def test_tw_print(capsys):
    for lb_command in [
        ["wt", *reddit_db, "-p"],
        ["dl", *reddit_db, "-p"],
        ["pl", *reddit_db],
        ["ds", *reddit_db],
    ]:
        lb(lb_command)
        captured = capsys.readouterr().out.replace("\n", "")
        assert "Aggregate" not in captured


class TestReddit(unittest.TestCase):
    @mock.patch("xklb.player.local_player", return_value=SimpleNamespace(returncode=0))
    def test_lb_fs(self, play_mocked):
        sys.argv[1:] = reddit_db
        watch()
        out = play_mocked.call_args[0][1]
        assert len(out) > 0

    def test_redditupdate(self):
        reddit_update([*reddit_db, "--lookback", "2", "--limit", "2"])
        db = connect(Namespace(database=reddit_db[1], verbose=2))

        playlists = list(db["playlists"].rows)
        assert playlists[0]["time_deleted"] == 0

        media = list(db["media"].rows)
        assert len(media) > 0
