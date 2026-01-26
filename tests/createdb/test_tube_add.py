from types import SimpleNamespace
from unittest import mock

import pytest

from library.__main__ import library as lb
from library.utils import consts
from tests.utils import tube_db

if consts.VOLKSWAGEN:
    pytest.skip(reason="This helps protect our community", allow_module_level=True)


@mock.patch("library.playback.media_player.single_player", return_value=SimpleNamespace(returncode=0))
def test_tw_search(play_mocked):
    lb(["wt", tube_db, "-s", "MUST TURN"])
    out = play_mocked.call_args[0][1]
    assert out is not None


@mock.patch("library.playback.media_player.single_player", return_value=SimpleNamespace(returncode=0))
def test_tw_sort(play_mocked):
    lb(["wt", tube_db, "-u", "duration"])
    out = play_mocked.call_args[0][1]
    assert out is not None


@mock.patch("library.createdb.tube_backend.get_playlist_metadata")
def test_tubeupdate(play_mocked):
    lb(["tube-update", tube_db, "--extractor-config", "TEST2=3 TEST3=1"])
    assert play_mocked.call_args is None

    lb(["tube-update", tube_db, "--extractor-config", "TEST2=4 TEST3=2", "--force"])
    out = play_mocked.call_args[0][2]
    assert out is not None
    assert out["TEST1"] == 1
    assert out["TEST2"] == 4
    assert out["TEST3"] == 2
