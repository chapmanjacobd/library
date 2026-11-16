import json
import sqlite3
from types import SimpleNamespace

from library.__main__ import library as lb
from library.download import download_status
from library.utils import consts
from tests.utils import connect_db_args, v_db


def test_download_status(assert_unchanged, capsys):
    lb(["download-status", v_db, "--to-json"])
    captured = capsys.readouterr().out.strip()
    assert_unchanged([json.loads(s) for s in captured.splitlines()])


def test_print_errors_excludes_hidden_media(temp_db, monkeypatch):
    db1 = temp_db()
    conn = sqlite3.connect(db1)
    conn.executescript(
        """
        CREATE TABLE playlists (id INTEGER PRIMARY KEY, time_deleted INTEGER);
        CREATE TABLE media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlists_id INTEGER,
            path TEXT,
            error TEXT,
            time_deleted INTEGER
        );
        INSERT INTO playlists VALUES (1, 0), (2, 1);
        INSERT INTO media (playlists_id, path, error, time_deleted) VALUES (1, 'a', 'err-a', 0);
        INSERT INTO media (playlists_id, path, error, time_deleted) VALUES (1, 'b', 'err-b', 1);
        INSERT INTO media (playlists_id, path, error, time_deleted) VALUES (2, 'c', 'err-c', 0);
        INSERT INTO media (playlists_id, path, error, time_deleted) VALUES (NULL, 'd', 'err-d', 0);
        INSERT INTO media (playlists_id, path, error, time_deleted) VALUES (0, 'e', 'err-e', 0);
        """
    )
    conn.commit()
    conn.close()

    args = connect_db_args(db1)
    args.verbose = consts.LOG_INFO
    args.hide_deleted = True
    captured = []
    monkeypatch.setattr(
        download_status.media_printer,
        "media_printer",
        lambda _args, media, **_kwargs: captured.extend(media),
    )

    download_status._print_errors(args)

    assert {(d["error"], d["count"]) for d in captured} == {
        ("err-a", 1),
        ("err-d", 1),
        ("err-e", 1),
        ("Other", 0),
    }


def test_download_status_handles_null_download_time(monkeypatch):
    args = SimpleNamespace(
        db=SimpleNamespace(
            query=lambda *_: [
                {
                    "path": "/local/download",
                    "webpath": "https://example.com/download",
                    "time_downloaded": None,
                },
                {
                    "path": "/local/legacy-download",
                    "webpath": "https://example.com/legacy-download",
                },
            ]
        ),
        download_retries=3,
        retry_delay="1 day",
        verbose=0,
    )
    captured = []
    monkeypatch.setattr(download_status, "parse_args", lambda: args)
    monkeypatch.setattr(download_status.sqlgroups, "construct_download_query", lambda *_args, **_kwargs: ("", {}))
    monkeypatch.setattr(download_status.nums, "human_to_seconds", lambda _: 1)
    monkeypatch.setattr(download_status.db_utils, "columns", lambda *_args: set())
    monkeypatch.setattr(
        download_status.media_printer,
        "media_printer",
        lambda _args, media, **_kwargs: captured.extend(media),
    )

    download_status.download_status()

    assert captured == []
