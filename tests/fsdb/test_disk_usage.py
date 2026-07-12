import json

import pytest

from library.__main__ import library as lb
from library.fsdb import folder_stats
from library.utils import consts
from tests.utils import connect_db_args, v_db

pytestmark = pytest.mark.skipif(consts.IS_WINDOWS, reason="Windows GitHub environment sometimes C:\\ sometimes D:\\")

platform = "linux"
if consts.IS_WINDOWS:
    platform = "windows"
elif consts.IS_MAC:
    platform = "mac"


def test_disk_usage(assert_unchanged, capsys):
    lb(["du", v_db, "-td", "--parents", "--depth=2", "--to-json"])
    captured = capsys.readouterr().out
    assert_unchanged(
        [json.loads(line) for line in captured.strip().split("\n")], basename=f"test_disk_usage.{platform}"
    )


def test_disk_usage_min_depth(capsys):
    from pathlib import Path

    lb(["du", v_db, "-td", "--parents", "--min-depth=3", "--to-json"])
    paths = {json.loads(line)["path"] for line in capsys.readouterr().out.strip().split("\n")}

    cwd = Path.cwd()
    depth_2 = Path(*cwd.parts[:2]).as_posix() + "/"
    depth_3 = Path(*cwd.parts[:3]).as_posix() + "/"

    assert depth_2 not in paths
    assert depth_3 in paths


def test_folder_stats_refreshes_after_media_change(temp_db):
    args = connect_db_args(temp_db())
    args.db.execute(
        """
        CREATE TABLE media (
            path TEXT NOT NULL,
            size INTEGER,
            duration INTEGER,
            time_deleted INTEGER
        )
        """
    )
    args.db.conn.executemany(
        "INSERT INTO media (path, size, duration, time_deleted) VALUES (?, ?, ?, ?)",
        [
            ("/root/a/file1.mp4", 1, 2, 0),
            ("/root/a/deep/file2.mp4", 2, 3, 0),
            ("/root/a/deleted.mp4", 100, 100, 1),
        ],
    )

    assert folder_stats.ensure(args.db)
    folder_stats.refresh_if_needed(args.db)
    stats = args.db.pop_dict("SELECT * FROM folder_stats WHERE parent = ?", ["/root/a"])
    assert stats["file_count"] == 2
    assert stats["direct_file_count"] == 1
    assert stats["total_size"] == 3
    assert stats["folder_count"] == 1

    args.db.execute("UPDATE media SET size = 7 WHERE path = ?", ["/root/a/file1.mp4"])
    assert args.db.pop("SELECT dirty FROM folder_stats_meta WHERE id = 1") == 1

    folder_stats.refresh_if_needed(args.db)
    assert args.db.pop("SELECT total_size FROM folder_stats WHERE parent = ?", ["/root/a"]) == 9
