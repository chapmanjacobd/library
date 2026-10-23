from types import SimpleNamespace
from unittest import mock

import pytest

from library.__main__ import library as lb
from library.utils import consts
from tests.utils import tube_db

if consts.VOLKSWAGEN:
    pytest.skip(reason="This helps protect our community", allow_module_level=True)


@mock.patch("library.play.media_player.single_player", return_value=SimpleNamespace(returncode=0))
def test_tw_search(play_mocked):
    lb(["wt", "--db", tube_db, "-s", "MUST TURN"])
    out = play_mocked.call_args[0][1]
    assert out is not None


@mock.patch("library.play.media_player.single_player", return_value=SimpleNamespace(returncode=0))
def test_tw_sort(play_mocked):
    lb(["wt", "--db", tube_db, "-u", "duration"])
    out = play_mocked.call_args[0][1]
    assert out is not None


@mock.patch("library.database.add.tube_backend.get_playlist_metadata")
def test_tubeupdate(play_mocked):
    import time

    import sqlite_utils

    db = sqlite_utils.Database(tube_db)
    db["playlists"].update(1, {"time_modified": int(time.time())})

    lb(["tube-update", tube_db, "--extractor-config", "TEST2=3 TEST3=1"])
    assert play_mocked.call_args is None

    lb(["tube-update", tube_db, "--extractor-config", "TEST2=4 TEST3=2", "--force"])
    out = play_mocked.call_args[0][2]
    assert out is not None
    assert out["TEST1"] == 1
    assert out["TEST2"] == 4
    assert out["TEST3"] == 2


@mock.patch(
    "library.database.add.tube_add.db_playlists.get_all",
    return_value=[
        {"path": "same-playlist", "extractor_config": '{"profile": "audio"}'},
        {"path": "same-playlist", "extractor_config": '{"profile": "video"}'},
    ],
)
@mock.patch("library.database.add.tube_backend.get_playlist_metadata")
def test_tubeupdate_retrieves_each_path_once(play_mocked, playlists_mocked):
    lb(["tube-update", tube_db, "--force"])

    assert playlists_mocked.call_count == 1
    assert play_mocked.call_count == 1


@mock.patch("library.database.add.tube_backend.get_playlist_metadata")
def test_tubeadd_retrieves_each_path_once(play_mocked, tmp_path):
    database = str(tmp_path / "tube.db")
    lb(["tube-add", database, "--force", "same-playlist", "same-playlist"])

    assert play_mocked.call_count == 1
