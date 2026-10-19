import pytest

from library.__main__ import library as lb
from library.file import media_compare


def test_media_hash_prints_digest(monkeypatch, capsys):
    monkeypatch.setattr(media_compare, "_frame_md5", lambda path: path.encode())

    lb(["file", "media-hash", "one.mp4", "two.mp4"])

    output = capsys.readouterr().out.splitlines()
    assert output[0].endswith("\tone.mp4")
    assert output[1].endswith("\ttwo.mp4")
    assert output[0].split("\t")[0] != output[1].split("\t")[0]


def test_media_compare_accepts_equal_decoded_streams(monkeypatch, capsys):
    monkeypatch.setattr(media_compare, "_frame_md5", lambda _path: b"same")

    lb(["file", "media-compare", "one.mp4", "two.mp4"])

    assert capsys.readouterr().out == "Media streams are equal\n"


def test_media_compare_returns_failure_for_different_streams(monkeypatch, capsys):
    monkeypatch.setattr(media_compare, "_frame_md5", lambda path: path.encode())

    with pytest.raises(SystemExit) as exc_info:
        lb(["file", "media-compare", "one.mp4", "two.mp4"])

    assert exc_info.value.code == 1
    assert "Media streams differ" in capsys.readouterr().out
