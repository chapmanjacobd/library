import os.path

import pytest

from library.__main__ import library as lb

paths = ["test.gif", "test.opus"]


def test_sample_compare():
    with pytest.raises(SystemExit):
        lb(["sample-compare"] + [os.path.join("tests/data", p) for p in paths])


def test_sample_cmp_missing_file(caplog, tmp_path):
    from library.files import sample_compare

    f1 = tmp_path / "one"
    f2 = tmp_path / "two"
    missing = tmp_path / "missing"
    with open(f1, "w") as f:
        f.write("hello world")
    with open(f2, "w") as f:
        f.write("hello world")

    assert sample_compare.sample_cmp(f1, f2, missing) is True
    assert f"File not found {missing}" in caplog.text


def test_sample_cmp_not_enough_existing_files(caplog, tmp_path):
    from library.files import sample_compare

    existing = tmp_path / "existing"
    missing = tmp_path / "missing"
    existing.write_text("hello world")

    with pytest.raises(ValueError, match="Not enough paths\\. Include 2 or more paths to compare"):
        sample_compare.sample_cmp(existing, missing)

    assert f"File not found {missing}" in caplog.text


def test_sample_cmp_logs_single_missing_file(caplog):
    from library.files import sample_compare

    with pytest.raises(ValueError, match="Not enough paths\\. Include 2 or more paths to compare"):
        sample_compare.sample_cmp("/path/that/does/not/exist")

    assert "File not found /path/that/does/not/exist" in caplog.text
