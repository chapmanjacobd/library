from library.__main__ import library as lb


def test_disk_usage(capsys):
    lb(["fs", "tests/data/test.mp4", "--to-json"])
    captured = capsys.readouterr().out
    assert "video/mp4" in captured.strip()
