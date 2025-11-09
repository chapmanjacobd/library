import unittest
from argparse import Namespace
from types import SimpleNamespace
from unittest import mock

from library.__main__ import library as lb
from library.utils.db_utils import connect

reddit_db = "tests/data/reddit.db"


@pytest.mark.skip("Requires reddit auth")
class TestReddit(unittest.TestCase):
    def setUp(self):
        lb(["reddit_add", reddit_db, "https://old.reddit.com/user/BuonaparteII/", "--limit", "10"])
        lb(["reddit_add", reddit_db, "https://old.reddit.com/r/pytest/", "--limit", "1"])

    @mock.patch("library.playback.media_player.single_player", return_value=SimpleNamespace(returncode=0))
    def test_lb_fs(self, play_mocked):
        lb(["wt", reddit_db])
        out = play_mocked.call_args[0][1]
        assert len(out) > 0

    def test_redditupdate(self):
        lb(["reddit_update", reddit_db, "--lookback", "2", "--limit", "2"])
        db = connect(Namespace(database=reddit_db, verbose=2))

        playlists = list(db["playlists"].rows)
        assert playlists[0]["time_deleted"] == 0

        media = list(db["media"].rows)
        assert len(media) > 0

    def test_print(self):
        lb(["wt", reddit_db, "-p"])
        lb(["dl", reddit_db, "-p"])
        lb(["pl", reddit_db])
        lb(["ds", reddit_db])
