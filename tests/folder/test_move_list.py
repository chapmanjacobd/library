from types import SimpleNamespace

from library.folder.move_list import group_by_folder


def test_group_by_folder_ignores_urls_and_applies_file_count_filter():
    args = SimpleNamespace(file_counts=lambda count: count >= 2)
    media = [
        {"path": "/media/one/a.mp4", "size": 100},
        {"path": "/media/one/b.mp4", "size": 200},
        {"path": "https://example.com/file.mp4", "size": 999},
    ]

    groups = group_by_folder(args, media)

    assert {group["path"]: group for group in groups} == {
        "/media/one/": {"path": "/media/one/", "size": 300, "count": 2},
        "/media/": {"path": "/media/", "size": 300, "count": 2},
    }
