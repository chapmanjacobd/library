from argparse import Namespace

from library.utils.filter_engine import (
    compare_block_strings,
    eval_sql_expr,
    filter_items_by_criteria,
    filter_mimetype,
    human_to_lambda_part,
    human_to_sql_part,
    is_mime_match,
    sort_items_by_criteria,
)


def test_human_to_lambda_part():
    dummy_conv = lambda x: int(x)  # identity converter for simplicity in tests

    assert human_to_lambda_part(10, dummy_conv, ">5") is True
    assert human_to_lambda_part(10, dummy_conv, "<5") is False
    assert human_to_lambda_part(10, dummy_conv, "+10") is True
    assert human_to_lambda_part(10, dummy_conv, "-10") is True
    assert human_to_lambda_part(10, dummy_conv, "10%10") is True  # between 9 and 11
    assert human_to_lambda_part(12, dummy_conv, "10%10") is False  # between 9 and 11
    assert human_to_lambda_part(10, dummy_conv, "10") is True


def test_human_to_sql_part():
    dummy_conv = lambda x: int(x)

    assert human_to_sql_part(dummy_conv, "size", ">5").strip() == "and size > 5"
    assert human_to_sql_part(dummy_conv, "size", "10%10").strip() == "and 9 <= size and size <= 11"


def test_compare_block_strings():
    assert compare_block_strings("video", "video/mp4") is True
    assert compare_block_strings("video", "audio/mp3") is False

    # Wildcards
    assert compare_block_strings("%mp4", "video.mp4") is True
    assert compare_block_strings("video%", "video.mp4") is True
    assert compare_block_strings("%video%", "some_video_file") is True
    assert compare_block_strings("video%mp4", "video_123.mp4") is True

    # Case insensitive
    assert compare_block_strings("VIDEO", "video/mp4") is True


def test_eval_sql_expr():
    item = {"path": "/home/user/video.mp4", "size": 1024, "type": "video/mp4", "duration": 60, "tags": None}

    # Equality
    assert eval_sql_expr("size", "=", "1024", item) is True
    assert eval_sql_expr("size", "==", "1024", item) is True
    assert eval_sql_expr("size", "=", "512", item) is False
    assert eval_sql_expr("type", "=", "video/mp4", item) is True

    # Inequality
    assert eval_sql_expr("size", "!=", "512", item) is True
    assert eval_sql_expr("size", "<>", "512", item) is True
    assert eval_sql_expr("size", "!=", "1024", item) is False

    # Comparison
    assert eval_sql_expr("size", ">", "512", item) is True
    assert eval_sql_expr("size", "<", "2048", item) is True
    assert eval_sql_expr("size", ">=", "1024", item) is True
    assert eval_sql_expr("size", "<=", "1024", item) is True

    # LIKE
    assert eval_sql_expr("path", "LIKE", "%video%", item) is True
    assert eval_sql_expr("path", "LIKE", "%.mp4", item) is True
    assert eval_sql_expr("path", "LIKE", "/home/%", item) is True
    assert eval_sql_expr("path", "LIKE", "%audio%", item) is False

    # IS NULL
    assert eval_sql_expr("tags", "IS", "NULL", item) is True
    assert eval_sql_expr("path", "IS", "NULL", item) is False


def test_filter_mimetype():
    files = [
        {"path": "1.mp4", "type": "video/mp4"},
        {"path": "2.jpg", "type": "image/jpeg"},
        {"path": "3.mp3", "type": "audio/mpeg"},
        {"path": "4.txt", "type": "text/plain"},
    ]

    # Filter by type
    args = Namespace(type=["video"], no_type=[])
    filtered = filter_mimetype(args, files)
    assert len(filtered) == 1
    assert filtered[0]["path"] == "1.mp4"

    # Filter by multiple types
    args = Namespace(type=["video", "audio"], no_type=[])
    filtered = filter_mimetype(args, files)
    assert len(filtered) == 2

    # Exclude type
    args = Namespace(type=[], no_type=["image"])
    filtered = filter_mimetype(args, files)
    assert len(filtered) == 3
    assert "2.jpg" not in [f["path"] for f in filtered]

    # Substring match
    args = Namespace(type=["mpeg"], no_type=[])
    filtered = filter_mimetype(args, files)
    assert len(filtered) == 1
    assert filtered[0]["path"] == "3.mp3"


def test_sort_files_by_criteria():
    files = [
        {"path": "a", "size": 100, "duration": 10},
        {"path": "b", "size": 50, "duration": 20},
        {"path": "c", "size": 150, "duration": 15},
    ]

    # Sort by size ASC
    args = Namespace(sort="size")
    sorted_files = sort_items_by_criteria(args, files)
    assert [f["path"] for f in sorted_files] == ["b", "a", "c"]

    # Sort by size DESC
    args = Namespace(sort="size desc")
    sorted_files = sort_items_by_criteria(args, files)
    assert [f["path"] for f in sorted_files] == ["c", "a", "b"]

    # Sort by duration DESC, size ASC
    args = Namespace(sort="duration desc, size")
    sorted_files = sort_items_by_criteria(args, files)
    assert [f["path"] for f in sorted_files] == ["b", "c", "a"]

    # Sort by operator expression
    # size > 75 ASC -> (False, True, True) -> a, b, c (wait, False comes before True)
    # Actually b's size is 50 (> 75 is False), a is 100 (True), c is 150 (True)
    # (False, True, True) -> b, a, c (a and c both True, original order preserved if stable)
    args = Namespace(sort="size > 75")
    sorted_files = sort_items_by_criteria(args, files)
    assert [f["path"] for f in sorted_files] == ["b", "a", "c"]


def test_filter_items_by_criteria():
    files = [
        {"path": "a.mp4", "size": 1000, "type": "video/mp4", "time_created": 100},
        {"path": "b.mp3", "size": 2000, "type": "audio/mpeg", "time_created": 200},
        {"path": "c.jpg", "size": 3000, "type": "image/jpeg", "time_created": 300},
    ]

    # Filter by size
    args = Namespace(defaults=[], sizes=lambda x: x > 1500, type=[], no_type=[], to_json=False, sort=[], limit=None)
    filtered = filter_items_by_criteria(args, files)
    assert len(filtered) == 2
    assert [f["path"] for f in filtered] == ["b.mp3", "c.jpg"]

    # Filter by type and size
    args.type = ["audio"]
    filtered = filter_items_by_criteria(args, files)
    assert len(filtered) == 1
    assert filtered[0]["path"] == "b.mp3"


def test_is_mime_match():
    # Substring matches
    assert is_mime_match(["video"], "video/mp4") is True
    assert is_mime_match(["mp4"], "video/mp4") is True
    assert is_mime_match(["audio"], "video/mp4") is False

    # Case sensitivity (lowercase in search list means case-insensitive)
    assert is_mime_match(["VIDEO"], "video/mp4") is False
    assert is_mime_match(["video"], "VIDEO/MP4") is True

    # Multiple words in mime type
    assert is_mime_match(["plain"], "text/plain") is True
    assert is_mime_match(["text"], "text/plain") is True


def test_time_filtering():
    files = [
        {"path": "old", "time_created": 100},
        {"path": "new", "time_created": 1000},
    ]

    from library.utils import consts

    consts.APPLICATION_START = 2000

    # Created within 1500 units (2000 - 1000 = 1000, which is < 1500)
    args = Namespace(
        defaults=["sizes"],  # Skip size filtering
        type=[],
        no_type=[],
        time_created=lambda x: x < 1500,
        to_json=False,
        sort=[],
        limit=None,
    )
    filtered = filter_items_by_criteria(args, files)
    assert len(filtered) == 1
    assert filtered[0]["path"] == "new"

    # Created before (older than) 1500 units (2000 - 100 = 1900, which is > 1500)
    args.time_created = lambda x: x > 1500
    filtered = filter_items_by_criteria(args, files)
    assert len(filtered) == 1
    assert filtered[0]["path"] == "old"
