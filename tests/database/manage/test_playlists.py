import sqlite3
from types import SimpleNamespace
from unittest import mock

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


@mock.patch("library.play.media_printer.media_printer")
def test_playlists_search_excludes_nonmatching_playlists(mocked, temp_db):
    db1 = temp_db()
    conn = sqlite3.connect(db1)
    conn.executescript(
        """
        CREATE TABLE playlists (
            id INTEGER PRIMARY KEY,
            path TEXT,
            title TEXT,
            extractor_key TEXT,
            time_deleted INTEGER
        );
        CREATE TABLE media (
            id INTEGER PRIMARY KEY,
            playlists_id INTEGER,
            path TEXT,
            size INTEGER
        );
        INSERT INTO playlists VALUES (1, 'matching-playlist', 'match', 'test', 0);
        INSERT INTO playlists VALUES (2, 'other-playlist', 'other', 'test', 0);
        INSERT INTO media VALUES (1, 1, 'file-1', 100);
        INSERT INTO media VALUES (2, 2, 'file-2', 200);
        INSERT INTO media VALUES (3, NULL, 'file-3', 300);
        """
    )
    conn.commit()
    conn.close()

    lb(["playlists", db1, "matching"])

    out = mocked.call_args[0][1]
    assert len(out) == 1
    assert out[0]["path"] == "matching-playlist"
    assert out[0]["size"] == 100
    assert out[0]["count"] == 1


def test_playlist_identity_includes_extractor_config():
    args = SimpleNamespace(database=":memory:", verbose=0, extractor_config={})
    args.db = db_utils.connect(args)
    db_playlists.create(args)
    db_utils.optimize(args)

    first_id = db_playlists.add_entry(args, {"path": "same-path", "extractor_config": {"source": "first"}})
    second_id = db_playlists.add_entry(args, {"path": "same-path", "extractor_config": {"source": "second"}})

    assert first_id != second_id
    assert db_playlists.get_id(args, "same-path", {"source": "first"}) == first_id
    assert db_playlists.get_id(args, "same-path", {"source": "second"}) == second_id
    assert db_playlists.exists(args, "same-path", {"source": "first"})
    assert not db_playlists.exists(args, "same-path", {"source": "missing"})


def test_playlist_identity_migrates_path_only_unique_index():
    args = SimpleNamespace(database=":memory:", verbose=0, extractor_config={})
    args.db = db_utils.connect(args)
    db_playlists.create(args)
    args.db.execute("CREATE UNIQUE INDEX idx_playlists_path ON playlists (path)")

    db_playlists.create(args)
    first_id = db_playlists.add(args, "same-path", {"extractor_config": {"source": "first"}})
    second_id = db_playlists.add(args, "same-path", {"extractor_config": {"source": "second"}})

    assert first_id != second_id
