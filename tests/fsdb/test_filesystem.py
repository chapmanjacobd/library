from library.__main__ import library as lb


def test_files_info(capsys):
    lb(["database", "filesystem", "list", "tests/data/test.mp4", "--to-json"])
    captured = capsys.readouterr().out
    assert "video/mp4" in captured.strip()
