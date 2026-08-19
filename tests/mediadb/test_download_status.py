import json
from types import SimpleNamespace

from library.__main__ import library as lb
from library.mediadb import download_status
from tests.utils import v_db


def test_download_status(assert_unchanged, capsys):
    lb(["download-status", v_db, "--to-json"])
    captured = capsys.readouterr().out.strip()
    assert_unchanged([json.loads(s) for s in captured.splitlines()])


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
