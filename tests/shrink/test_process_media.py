import pytest

from library.__main__ import library as lb
from library.shrink import process_media
from library.utils import devices


def test_shrink(temp_db, capsys):
    db1 = temp_db()
    lb(["row-add", db1, "--path", "test.mp4", "--duration", "2", "--size", "2000000"])

    with pytest.raises(devices.InteractivePrompt):
        lb(["shrink", "media", db1, "-s", "test.mp4"])
    captured = capsys.readouterr().out
    assert "Video: mp4" in captured.replace("\n", "")
    assert len(captured) > 150


def test_extract_nested_media_adds_files_after_recursive_extraction(tmp_path, monkeypatch):
    archive_path = tmp_path / "root.zip"
    archive_path.write_bytes(b"archive")
    output_path = tmp_path / "root"
    nested_path = output_path / "nested" / "clip.mkv"
    nested_path.parent.mkdir(parents=True)
    nested_path.write_bytes(b"video")

    calls = []

    def fake_extract(path, **_kwargs):
        calls.append(path)
        return str(output_path), []

    def fake_check_shrink(_args, media):
        return [
            {
                **media,
                "media_type": "Video",
                "ext": "mkv",
                "future_size": 1,
                "savings": media["size"] - 1,
                "processing_time": 1,
            }
        ]

    monkeypatch.setattr(process_media.processes, "extract_nested_archives", fake_extract)
    monkeypatch.setattr(process_media, "check_shrink", fake_check_shrink)

    args = type("Args", (), {"simulate": False})()
    media = process_media.extract_nested_media(
        args,
        [{"path": str(output_path / "direct.mkv"), "size": 5, "compressed_size": 2}],
        [str(archive_path)],
        type("MediaArgs", (), {})(),
    )

    assert calls == [str(archive_path)]
    assert {item["path"] for item in media} == {
        str(output_path / "direct.mkv"),
        str(nested_path),
    }
