import sqlite3

from library.filesystem import casefold


def test_find_case_conflicts_is_deterministic(tmp_path):
    (tmp_path / "video").mkdir()
    (tmp_path / "Video").mkdir()
    (tmp_path / "video" / "lower.txt").write_text("lower")
    (tmp_path / "Video" / "upper.txt").write_text("upper")

    conflicts = casefold.find_case_conflicts(tmp_path)

    assert list(conflicts) == ["video"]
    assert conflicts["video"] == sorted([str(tmp_path / "Video"), str(tmp_path / "video")])
    assert casefold.choose_preferred_path(conflicts["video"]) == str(tmp_path / "Video")


def test_apply_case_conflicts_dry_run_does_not_modify(tmp_path):
    preferred = tmp_path / "Video"
    source = tmp_path / "video"
    preferred.mkdir()
    source.mkdir()
    (source / "file.txt").write_text("content")
    conflicts = {"video": [str(preferred), str(source)]}

    actions = casefold.apply_case_conflicts(conflicts)

    assert (source / "file.txt").exists()
    assert any(action.action == "move" for action in actions)


def test_apply_case_conflicts_merges_directories(tmp_path):
    preferred = tmp_path / "Video"
    source = tmp_path / "video"
    preferred.mkdir()
    source.mkdir()
    (source / "file.txt").write_text("content")
    conflicts = {"video": [str(preferred), str(source)]}

    actions = casefold.apply_case_conflicts(conflicts, dry_run=False)

    assert (preferred / "file.txt").read_text() == "content"
    assert not source.exists()
    assert any(action.action == "merge" for action in actions)


def test_find_case_conflicts_from_db_reads_media_paths(tmp_path):
    preferred = tmp_path / "Media" / "Movie.mkv"
    conflict = tmp_path / "Media" / "movie.mkv"
    preferred.parent.mkdir()
    preferred.touch()
    conflict.touch()
    database = tmp_path / "media.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE media (path TEXT, time_deleted INTEGER)")
        connection.executemany(
            "INSERT INTO media VALUES (?, ?)",
            [(str(preferred), 0), (str(conflict), 0), (str(tmp_path / "deleted.mkv"), 1)],
        )

    conflicts = casefold.find_case_conflicts_from_db(str(database))

    assert conflicts["movie.mkv"] == sorted([str(conflict), str(preferred)])
    assert "deleted" not in conflicts


def test_parse_args_accepts_database_without_directory(tmp_path):
    args = casefold.parse_args(["--db", str(tmp_path / "media.db")])

    assert args.directory is None
    assert args.database == str(tmp_path / "media.db")
