from library.misc.dedupe_czkawka import extract_group_data, parse_czkawka_line


def test_parse_czkawka_line_supports_image_entries():
    assert parse_czkawka_line("/tmp/photo.jpg - 1920x1080 - 1.5 MiB - JPEG") == (
        "/tmp/photo.jpg",
        1.5,
        "MiB",
    )


def test_extract_group_data_converts_sizes_to_bytes():
    group = "/tmp/a.jpg - 1920x1080 - 1 MiB - JPEG\n/tmp/b.jpg - 2 KiB"

    assert extract_group_data(group) == [
        {"path": "/tmp/a.jpg", "size": 1024 * 1024},
        {"path": "/tmp/b.jpg", "size": 2 * 1024},
    ]
