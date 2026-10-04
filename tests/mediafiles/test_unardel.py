import logging, os
from pathlib import Path

from library.mediafiles import unardel
from library.mediafiles.unardel import replace_media_paths
from library.utils import objects


def test_replace_media_paths_builds_new_media_list():
    media = [
        {"path": "/output/wrapper/file.txt", "size": 1},
        {"path": "/output/other.txt", "size": 2},
    ]
    path_updates = [{"path": "/output/wrapper", "new_path": "/output"}]

    updated_media = replace_media_paths(media, path_updates)

    assert updated_media == [
        {"path": "/output/file.txt", "size": 1},
        {"path": "/output/other.txt", "size": 2},
    ]
    assert media[0]["path"] == "/output/wrapper/file.txt"


def test_replace_media_paths_applies_at_most_one_update_per_item():
    media = [{"path": "/out/file.txt", "size": 1}]
    path_updates = [{"path": "/out", "new_path": "/out/sub"}, {"path": "/out/sub", "new_path": "/out"}]

    updated_media = replace_media_paths(media, path_updates)

    assert updated_media == [{"path": "/out/sub/file.txt", "size": 1}]


def make_archived_media(archive_path, paths, compressed_size=5):
    return [
        {
            "path": path,
            "size": 10,
            "compressed_size": compressed_size,
            "ext": "mkv",
            "type": "video/x-matroska",
            "archive_path": str(archive_path),
        }
        for path in paths
    ]


def patch_unardel(monkeypatch, media, **arg_attrs):
    arg_attrs.setdefault("no_confirm", True)
    monkeypatch.setattr(unardel, "parse_args", lambda: objects.NoneSpace(**arg_attrs))
    monkeypatch.setattr(unardel, "collect_media", lambda _args: media)
    monkeypatch.setattr(unardel.printing, "table", lambda *_a, **_kw: None)


def test_unardel_unarchives_each_archive_once_and_rewrites_media_paths(tmp_path, monkeypatch, caplog):
    archive_path = tmp_path / "movie.zip"
    archive_path.write_bytes(b"zip")
    output_path = tmp_path / "movie"
    wrapper_path = output_path / "wrapper"
    wrapper_path.mkdir(parents=True)
    (output_path / "movie.mkv").write_bytes(b"video")
    (output_path / "sample.mkv").write_bytes(b"video")

    media = make_archived_media(
        archive_path,
        [str(wrapper_path / "movie.mkv"), str(wrapper_path / "sample.mkv")],
    )
    calls = []

    def fake_unar_delete(path, single_file_flatten=False, flatten=True):
        calls.append((path, single_file_flatten))
        return str(output_path), [{"path": str(wrapper_path), "new_path": str(output_path)}]

    patch_unardel(monkeypatch, media, simulate=False)
    monkeypatch.setattr(unardel.processes, "unar_delete", fake_unar_delete)

    caplog.set_level(logging.ERROR, logger="library")
    unardel.unardel()

    assert calls == [(str(archive_path), True)]
    assert not [r for r in caplog.records if "FileNotFoundError" in r.getMessage()]


def test_unardel_simulate_does_not_extract(tmp_path, monkeypatch):
    archive_path = tmp_path / "movie.zip"
    archive_path.write_bytes(b"zip")
    media = make_archived_media(archive_path, [str(tmp_path / "movie" / "movie.mkv")])

    def fail_unar_delete(*_args, **_kwargs):
        raise AssertionError("unar_delete should not run in simulate mode")

    patch_unardel(monkeypatch, media, simulate=True)
    monkeypatch.setattr(unardel.processes, "unar_delete", fail_unar_delete)

    unardel.unardel()


def test_unardel_reports_missing_media_after_unarchive(tmp_path, monkeypatch, caplog):
    archive_path = tmp_path / "movie.zip"
    archive_path.write_bytes(b"zip")
    media = make_archived_media(archive_path, [str(tmp_path / "movie" / "wrapper" / "movie.mkv")])

    moved = []
    patch_unardel(monkeypatch, media, simulate=False, move=str(tmp_path / "moved"))
    monkeypatch.setattr(unardel.processes, "unar_delete", lambda *_a, **_kw: (str(tmp_path / "movie"), []))
    monkeypatch.setattr(unardel.shell_utils, "rename_move_file", lambda src, dst: moved.append((src, dst)))

    caplog.set_level(logging.ERROR, logger="library")
    unardel.unardel()

    assert moved == []  # broken media is not moved to --move
    assert [r.getMessage() for r in caplog.records if "FileNotFoundError" in r.getMessage()]
    assert not Path(str(tmp_path / "moved")).exists()


def test_unardel_moves_existing_media_to_move_dir(tmp_path, monkeypatch):
    archive_path = tmp_path / "movie.zip"
    archive_path.write_bytes(b"zip")
    media_path = tmp_path / "movie" / "wrapper" / "movie.mkv"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"video")
    (tmp_path / "movie" / "movie.mkv").write_bytes(b"video")
    media = make_archived_media(archive_path, [str(media_path)])

    moved = []
    patch_unardel(monkeypatch, media, simulate=False, move=str(tmp_path / "moved"))
    monkeypatch.setattr(
        unardel.processes,
        "unar_delete",
        lambda *_a, **_kw: (str(tmp_path / "movie"), [{"path": str(media_path.parent), "new_path": str(tmp_path / "movie")}]),
    )
    monkeypatch.setattr(unardel.shell_utils, "rename_move_file", lambda src, dst: moved.append((src, str(dst))))

    unardel.unardel()

    assert len(moved) == 1
    assert moved[0][0] == str(tmp_path / "movie" / "movie.mkv")
    assert str(moved[0][1]).startswith(str(tmp_path / "moved") + os.sep)
    assert str(moved[0][1]).endswith(os.path.join("movie", "movie.mkv"))