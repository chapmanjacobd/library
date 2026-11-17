import sqlite_utils
import tempfile
from types import SimpleNamespace

from library.play import media_printer


def test_iter_existing_media_is_lazy(tmp_path):
    existing = tmp_path / "existing.mp4"
    existing.touch()
    consumed = []

    def source():
        consumed.append("first")
        yield {"path": str(existing)}
        consumed.append("second")
        yield {"path": str(tmp_path / "missing.mp4")}

    media = media_printer.iter_existing_media(source())

    assert next(media)["path"] == str(existing)
    assert consumed == ["first"]


def test_filter_deleted_checks_every_path(tmp_path):
    existing = []
    for i in range(60):
        path = tmp_path / f"existing{i}.mp4"
        path.touch()
        existing.append({"path": str(path)})
    missing_path = str(tmp_path / "missing.mp4")

    kept, deleted = media_printer.filter_deleted([*existing, {"path": missing_path}])

    assert len(kept) == len(existing)
    assert deleted == [missing_path]


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
