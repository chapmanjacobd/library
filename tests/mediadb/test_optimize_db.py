import sys

from library.mediadb import optimize_db


def test_optimize_db_passes_parsed_arguments(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(optimize_db.db_utils, "optimize", captured.append)
    database = str(tmp_path / "optimize.db")
    tmp_path.joinpath("optimize.db").touch()
    monkeypatch.setattr(sys, "argv", ["optimize", database, "--fts", "--force"])

    optimize_db.optimize_db()

    assert len(captured) == 1
    assert captured[0].database == database
    assert captured[0].fts is True
    assert captured[0].force is True
