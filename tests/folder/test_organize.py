from library.folder.organize import analyze_folder, categorize_file
from library.__main__ import library as lb


def test_categorize_file_matches_existing_extension_profiles():
    assert categorize_file("track.opus") == "audio"
    assert categorize_file("movie.mkv") == "video"
    assert categorize_file("scan.jpg") == "images"
    assert categorize_file("book.epub") == "books"
    assert categorize_file("archive.zip") == "archives"


def test_organize_dry_run_does_not_move_folder(tmp_path, capsys):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "track.opus").write_bytes(b"audio")

    lb(["folder", "organize", str(source), "--simulate"])

    assert source.exists()
    assert not (tmp_path / "audio" / "downloads").exists()
    assert "track.opus" in capsys.readouterr().out


def test_analyze_folder_returns_mixed_for_balanced_categories(tmp_path):
    audio = tmp_path / "track.opus"
    video = tmp_path / "movie.mkv"
    image = tmp_path / "cover.jpg"
    audio.write_bytes(b"a")
    video.write_bytes(b"b")
    image.write_bytes(b"c")

    assert analyze_folder([audio, video, image]) == "mixed"
