import sys

from library.mediadb import history_add


def test_parse_args_reads_database_and_paths(monkeypatch, tmp_path):
    database = str(tmp_path / "history.db")
    monkeypatch.setattr(sys, "argv", ["history-add", database, "media.mp4"])

    args = history_add.parse_args()

    assert args.database == database
    assert args.paths == ["media.mp4"]
