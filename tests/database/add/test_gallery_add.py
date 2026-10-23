from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from library.database.add import gallery_backend
from library.database.manage import db_media, db_playlists
from library.utils.db_utils import connect
from library.utils.objects import NoneSpace


def create_args(test_name):
    db_path = f"tests/data/gdl_{test_name}.db"
    Path(db_path).unlink(missing_ok=True)
    Path(db_path).touch()

    args = NoneSpace(database=db_path, verbose=2)
    args.db = connect(args)

    db_playlists.create(args)
    db_media.create(args)
    return args


def test_safe_mode():
    """Version-robust check of the catch-all policy using the installed gallery-dl:
    `is_supported` must not claim direct links or generic pages (it is used for both
    `auto` routing and every `--safe` check)."""
    args = NoneSpace()
    gallery_backend.load_module_level_gallery_dl(args)

    # is_supported excludes gallery-dl's generic/directlink/ytdl catch-alls
    assert gallery_backend.is_supported("https://example.com/pic.png") is False
    assert gallery_backend.is_supported("https://example.com/page.html") is False
    assert gallery_backend.is_supported("generic:https://example.com/x") is False
    assert gallery_backend.is_supported("https://youtu.be/HoY5RbzRcmo") is False


@pytest.mark.skip("imgur is 429")
def test_get_playlist_metadata_imgur_single():
    args = create_args("playlist_metadata_imgur_single")
    out = gallery_backend.get_playlist_metadata(args, "https://imgur.com/0gybAXR")
    assert out == 1
    data = list(args.db.query("select * from media"))
    assert len(data) == 1
    assert data[0]["path"] == "https://i.imgur.com/0gybAXR.mp4"
    assert data[0]["webpath"] == "https://imgur.com/0gybAXR"


def test_get_playlist_metadata_wikimedia_album():
    args = create_args("get_playlist_metadata_wikimedia_album")
    out = gallery_backend.get_playlist_metadata(
        args,
        "https://commons.wikimedia.org/wiki/Category:Album_1_Uruguay,_Argentina,_Chile,_and_Peru,_1920-1921_:_includes_photographs_of_Wetmore,_James_Lee_Peters,_and_Wilfrid_B._Alexander",
    )
    assert out == 79
    media = list(args.db.query("select * from media"))
    assert len(media) == 79
    playlists = list(args.db.query("select * from playlists"))
    assert len(playlists) == 1


def test_is_supported_requires_init(monkeypatch):
    monkeypatch.delattr(gallery_backend.is_supported, "extractors", raising=False)
    monkeypatch.delattr(gallery_backend.is_supported, "configured", raising=False)
    with pytest.raises(RuntimeError, match="load_module_level_gallery_dl"):
        gallery_backend.is_supported("https://www.reddit.com")


def test_is_supported_single_arg():
    # gallery_backend.is_supported is registered as a 1-arg SQLite UDF
    # (called as is_supported(m.path)); it requires load_module_level_gallery_dl(args) first.
    import types

    gallery_backend.load_module_level_gallery_dl(types.SimpleNamespace(download_archive=None))

    import sqlite_utils

    db = sqlite_utils.Database(memory=True)
    db.register_function(gallery_backend.is_supported, deterministic=True)

    rows = list(db.query("select is_supported('https://www.reddit.com') as r"))
    assert rows[0]["r"] in (0, 1)


def test_is_supported_excludes_catch_all_extractors(monkeypatch):
    """gallery-dl's generic/directlink/ytdl extractors match (almost) any URL. is_supported
    must ignore them so ordinary pages are not claimed by the gallery backend."""
    import re

    class FakeExtractor:
        def __init__(self, category, pattern):
            self.category = category
            self.pattern = re.compile(pattern)

    monkeypatch.setattr(
        gallery_backend.is_supported,
        "extractors",
        [
            FakeExtractor("reddit", r"https://reddit\.com/.*"),
            FakeExtractor("ytdl", r".*"),
            FakeExtractor("directlink", r".*\.png$"),
            FakeExtractor("generic", r"generic:.*"),
        ],
        raising=False,
    )
    monkeypatch.setattr(gallery_backend.is_supported, "configured", True, raising=False)
    gallery_backend._is_supported_cached.cache_clear()  # noqa: SLF001
    try:
        assert gallery_backend.is_supported("https://reddit.com/r/library")
        assert not gallery_backend.is_supported("https://example.com/page")
        assert not gallery_backend.is_supported("https://example.com/pic.png")
        assert not gallery_backend.is_supported("generic:https://example.com/x")
    finally:
        gallery_backend._is_supported_cached.cache_clear()  # noqa: SLF001


def test_get_playlist_metadata_uses_child_status_and_extractor(monkeypatch):
    class Extractor:
        def __init__(self, category):
            self.category = category

        @classmethod
        def from_url(cls, _url):
            return cls("child")

    class Job:
        def __init__(self, extractor, parent=None):
            self.extractor = Extractor("root") if isinstance(extractor, str) else extractor
            self.parent = parent
            self.status = 0

        def run(self):
            if self.extractor.category == "root":
                self.handle_queue("https://example.com/child", {"_extractor": Extractor})
            else:
                self.status = 4
                self.handle_url("https://example.com/image.jpg", {"title": "image"})
            return self.status

    fake_gallery_dl = SimpleNamespace(job=SimpleNamespace(Job=Job))
    monkeypatch.setattr(gallery_backend, "load_module_level_gallery_dl", lambda _args: fake_gallery_dl)
    monkeypatch.setattr(gallery_backend.db_playlists, "add", Mock(return_value=1))
    monkeypatch.setattr(gallery_backend.db_media, "exists", Mock(return_value=False))
    playlist_media_add = Mock()
    monkeypatch.setattr(gallery_backend.db_media, "playlist_media_add", playlist_media_add)

    args = SimpleNamespace(ignore_errors=False)
    assert gallery_backend.get_playlist_metadata(args, "https://example.com/album") == 1

    info = playlist_media_add.call_args.args[2]
    assert info["extractor_key"] == "gdl_child"
    assert playlist_media_add.call_args.kwargs["error"] == "HTTPError"
