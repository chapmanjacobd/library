import pytest

from library.folder import big_dirs
from library.utils.objects import NoneSpace


def test_reaggregate_direct_parent_folders():
    media = [
        {
            "path": "/media/folder/file",
            "duration": 1,
            "size": 1,
            "time_deleted": 0,
            "time_last_played": 0,
        }
    ]
    args = NoneSpace(max_depth=None, min_depth=0)

    folders = big_dirs.group_files_by_parent(media)
    reaggregated = big_dirs.reaggregate_at_depth(args, folders)

    assert folders[0]["folders"] == 0
    assert reaggregated[0]["folders"] == 0


def test_group_files_by_parent_deleted_totals_are_per_folder():
    media = [
        {"path": "/media/a/keep", "duration": 1, "size": 1, "time_deleted": 0, "time_last_played": 0},
        {"path": "/media/a/deleted", "duration": 2, "size": 2, "time_deleted": 1, "time_last_played": 0},
        {"path": "/media/b/deleted", "duration": 4, "size": 4, "time_deleted": 1, "time_last_played": 0},
    ]

    folders = {d["path"]: d for d in big_dirs.group_files_by_parent(media)}

    assert folders["/media/a/"]["deleted_size"] == 2
    assert folders["/media/a/"]["deleted_duration"] == 2
    assert folders["/media/b/"]["deleted_size"] == 4
    assert folders["/media/b/"]["deleted_duration"] == 4


def test_reaggregate_at_depth_sums_deleted_totals():
    folders = [
        {
            "path": "/media/a/",
            "size": 1,
            "duration": 1,
            "total": 2,
            "exists": 1,
            "deleted": 1,
            "deleted_size": 10,
            "deleted_duration": 2,
            "played": 0,
            "folders": 0,
        },
        {
            "path": "/media/b/",
            "size": 2,
            "duration": 2,
            "total": 2,
            "exists": 1,
            "deleted": 1,
            "deleted_size": 20,
            "deleted_duration": 4,
            "played": 0,
            "folders": 0,
        },
    ]
    args = NoneSpace(max_depth=2, min_depth=0)

    merged = big_dirs.reaggregate_at_depth(args, folders)

    assert len(merged) == 1
    assert merged[0]["path"] == "/media/"
    assert merged[0]["deleted_size"] == 30
    assert merged[0]["deleted_duration"] == 6


def test_reaggregate_medians_are_order_independent():
    def folder(path, median):
        return {
            "path": path,
            "size": 1,
            "duration": 1,
            "median_size": median,
            "median_duration": median,
            "total": 1,
            "exists": 1,
            "deleted": 0,
            "deleted_size": 0,
            "deleted_duration": 0,
            "played": 0,
            "folders": 0,
        }

    args = NoneSpace(max_depth=2, min_depth=0)
    folders = [folder("/media/a/", 100), folder("/media/b/", 1)]

    forward = big_dirs.reaggregate_at_depth(args, folders)[0]
    reverse = big_dirs.reaggregate_at_depth(args, list(reversed(folders)))[0]

    assert forward["median_size"] == pytest.approx(50.5)
    assert reverse["median_size"] == pytest.approx(50.5)


def test_group_files_by_parents_includes_shallowest_file_folder():
    media = [
        {"path": "/a/b/file", "duration": 1, "size": 1, "time_deleted": 0, "time_last_played": 0},
    ]

    folders = big_dirs.group_files_by_parents(media)

    assert [d["path"] for d in folders] == ["/a/b/"]


def test_group_files_by_parents_ignores_url_paths():
    media = [
        {"path": "/a/b/file", "duration": 1, "size": 1, "time_deleted": 0, "time_last_played": 0},
        {"path": "https://test/", "duration": 0, "size": 0, "time_deleted": 0, "time_last_played": 0},
    ]

    folders = big_dirs.group_files_by_parents(media)

    assert [d["path"] for d in folders] == ["/a/b/"]


def test_group_media_by_depth_counts_each_file_once():
    media = [
        {"path": "/a/b/f1", "duration": 1, "size": 10, "time_deleted": 0, "time_last_played": 0},
        {"path": "/a/b/c/d/f2", "duration": 2, "size": 20, "time_deleted": 0, "time_last_played": 0},
    ]
    args = NoneSpace(depth=True, max_depth=3, min_depth=0, hide_deleted=False)

    folders = big_dirs.process_big_dirs(args, [], media)

    assert len(folders) == 1
    assert folders[0]["path"] == "/a/b/"
    assert folders[0]["size"] == 30
    assert folders[0]["exists"] == 2
    assert folders[0]["folders"] == 1


def test_group_media_by_depth_recomputes_medians():
    media = [
        {"path": "/a/one", "duration": 10, "size": 100, "time_deleted": 0, "time_last_played": 0},
        {"path": "/b/two", "duration": 2, "size": 1, "time_deleted": 0, "time_last_played": 0},
    ]
    args = NoneSpace(depth=True, max_depth=1, min_depth=0, hide_deleted=False)

    folders = big_dirs.process_big_dirs(args, [], media)

    assert len(folders) == 1
    assert folders[0]["path"] == "/"
    assert folders[0]["median_size"] == pytest.approx(50.5)
    assert folders[0]["median_duration"] == 6
