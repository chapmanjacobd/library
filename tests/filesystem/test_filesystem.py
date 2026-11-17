from library.__main__ import library as lb


def test_files_info(capsys):
    lb(["filesystem", "list", "tests/data/test.mp4", "--to-json"])
    captured = capsys.readouterr().out
    assert "video/mp4" in captured.strip()


def test_filesystem_print_fields_excludes_missing(tmp_path, temp_db, capsys):
    database = temp_db()
    existing = tmp_path / "existing.txt"
    missing = tmp_path / "missing.txt"
    existing.write_text("x")
    missing.write_text("x")

    lb(["fs-add", "--fs", database, str(existing), str(missing)])
    missing.unlink()
    capsys.readouterr()

    for flags in (["-p", "fe"], ["-p", "f", "--exists"]):
        lb(["filesystem", "list", "--db", database, *flags])
        output = capsys.readouterr().out
        assert str(existing) in output
        assert str(missing) not in output
