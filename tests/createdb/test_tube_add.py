from types import SimpleNamespace
from unittest import mock

import pytest

from tests.utils import tube_db
from xklb.lb import library as lb
from xklb.utils import consts

if consts.VOLKSWAGEN:
    pytest.skip(reason="This helps protect our community", allow_module_level=True)


@mock.patch("xklb.playback.media_player.single_player", return_value=SimpleNamespace(returncode=0))
def test_lb_fs(play_mocked):
    lb(["wt", tube_db])
    out = play_mocked.call_args[0][1]
    assert "https://www.youtube.com/watch?v=QoXubRvB6tQ" in out["path"]
    assert out["duration"] == 28
    assert out["title"] == "Most Epic Video About Nothing"
    assert out["size"] > 2000000


@mock.patch("xklb.playback.media_player.single_player", return_value=SimpleNamespace(returncode=0))
def test_tw_search(play_mocked):
    lb(["wt", tube_db, "-s", "nothing"])
    out = play_mocked.call_args[0][1]
    assert out is not None


@mock.patch("xklb.playback.media_player.single_player", return_value=SimpleNamespace(returncode=0))
def test_tw_sort(play_mocked):
    lb(["wt", tube_db, "-u", "duration"])
    out = play_mocked.call_args[0][1]
    assert out is not None


@mock.patch("xklb.playback.media_player.single_player", return_value=SimpleNamespace(returncode=0))
def test_tw_size(play_mocked):
    lb(["wt", tube_db, "--size", "+1MB"])
    out = play_mocked.call_args[0][1]
    assert out is not None


@mock.patch("xklb.createdb.tube_backend.get_playlist_metadata")
def test_tubeupdate(play_mocked):
    lb(["tube-update", tube_db, "--extractor-config", "TEST2=3 TEST3=1"])
    assert play_mocked.call_args is None

    lb(["tube-update", tube_db, "--extractor-config", "TEST2=4 TEST3=2", "--force"])
    out = play_mocked.call_args[0][2]
    assert out is not None
    assert out["TEST1"] == "1"
    assert out["TEST2"] == "4"
    assert out["TEST3"] == "2"


@mock.patch("xklb.mediadb.download.mark_download_attempt")
@mock.patch("xklb.createdb.tube_backend.download")
@mock.patch("xklb.createdb.tube_backend.get_playlist_metadata")
def test_tube_dl_conversion(get_playlist_metadata, tube_download, mark_download_attempt):
    PLAYLIST_URL = "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm"
    PLAYLIST_VIDEO_URL = "https://www.youtube.com/watch?v=QoXubRvB6tQ"
    STORAGE_PREFIX = "tests/data/"

    lb(["tube_add", tube_db, PLAYLIST_URL])
    lb(["tube_add", tube_db, "--force", PLAYLIST_URL])
    out = get_playlist_metadata.call_args[0][1]
    assert out == PLAYLIST_URL

    lb(["download", tube_db, "--prefix", STORAGE_PREFIX, "--video"])
    mark_download_attempt.assert_called_once()
    out = tube_download.call_args[0]
    assert out[1]["path"] == PLAYLIST_VIDEO_URL
