from unittest import mock

from library.__main__ import library as lb


@mock.patch("library.playback.media_printer.media_printer")
def test_fsupdate_parentpath_first(mocked, temp_db):
    db1 = temp_db()
    lb(["fsadd", db1, "tests/"])
    lb(["fsadd", db1, "tests/data/"])

    lb(["playlists", db1])
    out = mocked.call_args[0][1]
    assert len(out) == 1
    assert out[0]["path"].endswith("tests")


@mock.patch("library.playback.media_printer.media_printer")
def test_fsupdate_subpath_first(mocked, temp_db):
    db1 = temp_db()
    lb(["fsadd", db1, "tests/data/"])
    lb(["fsadd", db1, "tests/"])

    lb(["playlists", db1])
    out = mocked.call_args[0][1]
    assert len(out) == 1
    assert out[0]["path"].endswith("tests")


@mock.patch("library.playback.media_printer.media_printer")
def test_fsupdate_multi(mocked, temp_db):
    db1 = temp_db()
    lb(["fsadd", "--fs", db1, "tests/data/", "tests/conftest.py"])
    lb(["fsadd", "--fs", db1, "library/assets/"])

    lb(["playlists", db1])
    out = mocked.call_args[0][1]
    assert len(out) == 3
