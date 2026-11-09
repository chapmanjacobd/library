import io
from types import SimpleNamespace
from unittest import mock

import pytest
import sqlite_utils
import yt_dlp

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


def test_tubeadd_discovers_youtube_music_collections(monkeypatch, tmp_path):
    music = "https://music.youtube.com/channel/UCoriginal"
    redirect = "https://www.youtube.com/channel/UCoriginal/videos"
    channel = "https://www.youtube.com/channel/UCother"
    json_channel = "https://www.youtube.com/channel/UCjson"
    playlist = "https://www.youtube.com/playlist?list=PLhtml"
    json_playlist = "https://www.youtube.com/playlist?list=PLjson"
    markup = b"""
        <a href="/channel/UCoriginal">self</a>
        <a href="/channel/UCother/videos">channel</a>
        <a href="https://m.youtube.com/channel/UCother">duplicate</a>
        <a href="/playlist?list=PLhtml&amp;index=1">playlist</a>
        <div data-url="/playlist?list=PLhtml">duplicate</div>
        <a href="https://example.com/playlist?list=PLexternal">external</a>
        <a href="/watch?v=video">video</a>
        <script>var ytInitialData = {"contents": [
          {"url": "/channel/UCjson"},
          {"url": "/playlist?list=PLjson\\u0026index=2"},
          {"url": "/playlist?list=PLhtml"}
        ]};</script>
    """
    extracted = []
    fetched = []
    extras = []

    def fake_extract_info(ydl, path, **_kwargs):
        extracted.append(path)
        if path == music:
            ydl.report_warning(f"[youtube:tab] YouTube Music is not directly supported. Redirecting to {redirect}")
        video_id = f"{len(extracted):011d}"
        ydl.run_all_pps(
            "pre_process",
            {
                "id": video_id,
                "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
                "playlist_id": f"playlist-{video_id}",
                "playlist_title": path,
                "extractor_key": "Youtube",
                "title": f"Video {video_id}",
            },
        )
        return {"id": video_id}

    def fake_urlopen(_ydl, url):
        fetched.append(url)
        return io.BytesIO(markup)

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract_info)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "urlopen", fake_urlopen)
    monkeypatch.setattr("library.database.add.tube_backend.get_extra_metadata", lambda _args, path: extras.append(path))

    database = str(tmp_path / "tube.db")
    lb(["database", "add", "video", database, "--extra", "--extractor-config", "no_warnings=True", music, channel])

    expected = {music, channel, json_channel, playlist, json_playlist}
    assert set(extracted) == expected
    assert len(extracted) == len(expected)
    assert set(extras) == expected
    assert fetched == [redirect]
    db = sqlite_utils.Database(database)
    assert {row["path"] for row in db["playlists"].rows} == expected
    assert db["media"].count == len(expected)


@pytest.mark.parametrize(
    ("warning", "should_fetch"),
    [
        (
            (
                "[youtube:tab] YouTube Music is not directly supported. "
                "Redirecting to https://www.youtube.com/channel/UCoriginal/videos"
            ),
            True,
        ),
        (
            "[youtube:tab] YouTube Music is not directly supported. Redirecting to https://example.com/channel/UCx",
            False,
        ),
        ("[youtube:tab] YouTube Music is not directly supported. Redirecting to https://[invalid", False),
        ("[youtube:tab] An unrelated warning", False),
    ],
)
def test_tubeadd_music_discovery_failure_preserves_original(monkeypatch, tmp_path, warning, should_fetch):
    music = "https://music.youtube.com/channel/UCoriginal"
    fetched = []

    def fake_extract_info(ydl, _path, **_kwargs):
        ydl.report_warning(warning)
        ydl.run_all_pps(
            "pre_process",
            {
                "id": "00000000001",
                "webpage_url": "https://www.youtube.com/watch?v=00000000001",
                "playlist_id": "original",
                "extractor_key": "Youtube",
                "title": "Original",
            },
        )
        return {"id": "original"}

    def fail_fetch(_ydl, url):
        fetched.append(url)
        raise OSError("network unavailable")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract_info)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "urlopen", fail_fetch)
    database = str(tmp_path / "tube.db")
    lb(["database", "add", "video", database, music])

    assert bool(fetched) is should_fetch
    db = sqlite_utils.Database(database)
    assert [row["path"] for row in db["playlists"].rows] == [music]
    assert db["media"].count == 1


def test_tubeupdate_does_not_discover_music(monkeypatch, tmp_path):
    music = "https://music.youtube.com/channel/UCoriginal"
    database = str(tmp_path / "tube.db")
    lb(["database", "add", "video", database, "--no-extract-playlists", music])
    extracted = []

    def fake_extract_info(ydl, path, **_kwargs):
        extracted.append(path)
        ydl.report_warning(
            "[youtube:tab] YouTube Music is not directly supported. "
            "Redirecting to https://www.youtube.com/channel/UCoriginal/videos"
        )
        return {"id": "original"}

    def unexpected_fetch(_ydl, _url):
        pytest.fail("tube-update must not discover additional links")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract_info)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "urlopen", unexpected_fetch)
    monkeypatch.setattr(
        "library.database.add.tube_add.db_playlists.get_all",
        lambda *_args, **_kwargs: [{"path": music, "extractor_config": "{}"}],
    )
    lb(["database", "update", "video", database, "--force"])

    assert extracted == [music]


@pytest.mark.parametrize("option", ["--no-extract", "--no-extract-playlists"])
def test_tubeadd_insert_only_does_not_discover_music(monkeypatch, tmp_path, option):
    def unexpected_extract(*_args, **_kwargs):
        pytest.fail("insert-only must not extract URLs")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", unexpected_extract)
    database = str(tmp_path / "tube.db")
    music = "https://music.youtube.com/channel/UCoriginal"
    lb(["database", "add", "video", database, option, music])

    db = sqlite_utils.Database(database)
    table = "media" if option == "--no-extract" else "playlists"
    assert [row["path"] for row in db[table].rows] == [music]
