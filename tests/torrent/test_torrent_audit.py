from types import SimpleNamespace

from library.torrent.torrent_audit import audit_torrents


def test_audit_torrents_reports_duplicate_and_orphan_files(tmp_path):
    root = tmp_path / "seeding"
    root.mkdir()
    (root / "shared.mkv").write_text("shared")
    (root / "orphan.mkv").write_text("orphan")

    torrents = [
        SimpleNamespace(name="one", save_path=str(root), download_path=None, content_path=None),
        SimpleNamespace(name="two", save_path=str(root), download_path=None, content_path=None),
    ]
    files = {
        "one": [SimpleNamespace(name="shared.mkv")],
        "two": [SimpleNamespace(name="shared.mkv")],
    }

    result = audit_torrents(torrents, file_getter=lambda torrent: files[torrent.name])

    assert list(result["duplicates"]) == [root / "shared.mkv"]
    assert result["duplicates"][root / "shared.mkv"] == {"one", "two"}
    assert result["orphans"] == [root / "orphan.mkv"]
