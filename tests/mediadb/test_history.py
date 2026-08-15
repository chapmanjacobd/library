from library.__main__ import library as lb


def test_history_accepts_frequency_flag(temp_db, capsys):
    # C5: usage.history documents `--frequency` but parse_args never registers the
    # arggroup, so the documented flag errored with "unrecognized arguments".
    db_path = temp_db()
    lb(["fs-add", db_path, "tests/data/"])
    lb(["history-add", db_path, "tests/data/test.mp4"])

    lb(["history", db_path, "--frequency", "daily"])
    captured = capsys.readouterr().out
    assert "History:" in captured