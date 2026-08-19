from library.folders import big_dirs
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

    folders = big_dirs.group_files_by_parent(args, media)
    reaggregated = big_dirs.reaggregate_at_depth(args, folders)

    assert folders[0]["folders"] == 0
    assert reaggregated[0]["folders"] == 0
