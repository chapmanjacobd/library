import sqlite_utils
import tempfile
from types import SimpleNamespace

from library.playback import media_printer


def test_moved_media_handles_quotes():
    # 4.1: moved_media embeds shlex.quote() output (shell quoting) directly into SQL,
    # so any path containing an apostrophe produces invalid SQL.
    db_path = tempfile.mktemp(".db")
    db = sqlite_utils.Database(db_path)
    db["media"].insert({"playlists_id": 1, "path": "/foo/o'brien/file.mp4"})
    args = SimpleNamespace(db=db)

    media_printer.moved_media(args, ["/foo/o'brien/file.mp4"], "/foo/o'brien", "/foo/renamed")

    rows = list(db["media"].rows)
    assert len(rows) == 1
    assert rows[0]["path"] == "/foo/renamed/file.mp4"
