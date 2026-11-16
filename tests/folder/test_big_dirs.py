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
    assert merged[0]["deleted_size"] == 30
    assert merged[0]["deleted_duration"] == 6
