from pathlib import Path

import pytest

from library.createdb import gallery_backend
from library.mediadb import db_media, db_playlists
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


@pytest.mark.skip("inconsistent between gallery-dl versions")
def test_safe_mode():
    args = NoneSpace()
    gallery_backend.load_module_level_gallery_dl(args)
    assert gallery_backend.is_supported("https://i.redd.it/gdlcqo5xvpwa1.png")
    assert gallery_backend.is_supported("https://www.reddit.com/gallery/145863a")
    assert gallery_backend.is_supported("https://old.reddit.com/r/lego/comments/145863a/spaceship_moc/")
    assert gallery_backend.is_supported("www.com") is False
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
