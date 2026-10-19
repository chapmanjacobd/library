from types import SimpleNamespace

from library.__main__ import library as lb
from library.database.manage import db_playlists
from library.utils import db_utils
from tests.utils import v_db


def test_playlists(capsys):
    lb(["playlists", v_db])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "duration" in captured
    assert len(captured) > 200


def test_playlists2(capsys):
    lb(["playlists", v_db, "data"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert len(captured) > 200


def test_playlists3(capsys):
    lb(["playlists", v_db, "-pa"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "playlists_count" in captured
    assert "media_count" in captured
    assert len(captured) > 200


def test_playlist_identity_includes_extractor_config():
    args = SimpleNamespace(database=":memory:", verbose=0, extractor_config={})
    args.db = db_utils.connect(args)
    db_playlists.create(args)

    first_id = db_playlists._add(args, {"path": "same-path", "extractor_config": {"source": "first"}})
    second_id = db_playlists._add(args, {"path": "same-path", "extractor_config": {"source": "second"}})

    assert first_id != second_id
    assert db_playlists.get_id(args, "same-path", {"source": "first"}) == first_id
    assert db_playlists.get_id(args, "same-path", {"source": "second"}) == second_id
    assert db_playlists.exists(args, "same-path", {"source": "first"})
    assert not db_playlists.exists(args, "same-path", {"source": "missing"})
