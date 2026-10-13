import sys

from library.__main__ import library as lb
from library.mediadb import history


def test_history_accepts_frequency_flag(temp_db, capsys, monkeypatch):
    # C5: usage.history documents `--frequency` but parse_args never registers the
    # arggroup, so the documented flag errored with "unrecognized arguments".
    db_path = temp_db()
    lb(['database', 'add', 'filesystem', db_path, "tests/data/"])
    lb(['database', 'history', 'add', db_path, "tests/data/test.mp4"])

    monkeypatch.setattr(sys, "argv", ["history", db_path, "--frequency", "daily"])
    history.history()
    captured = capsys.readouterr().out
    assert "History:" in captured
