import sqlite3
import sqlite_utils
import tempfile
from unittest import mock

from library.mediadb import block


def test_block_new_url_with_tube_metadata():
    # 4.1: p = [p] then p[1] = data[args.match_column] raises IndexError on the
    # normal "block a new URL" path whenever tube metadata contains the match column.
    db_path = tempfile.mktemp(".db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE media (id INTEGER PRIMARY KEY, playlists_id int, path text, webpath text, size int, playlist_path text, time_deleted int, time_modified int, time_downloaded int, time_created int)"
    )
    conn.execute("CREATE TABLE playlists (id int, path text)")
    conn.execute("CREATE TABLE blocklist (key text, value text)")
    conn.commit()
    conn.close()

    db = sqlite_utils.Database(db_path)
    db["media"].insert(
        {"playlists_id": 1, "path": "https://example.com/video.mp4", "size": 100, "time_deleted": 0}
    )

    with (
        mock.patch("library.utils.consts.PYTEST_RUNNING", False),  # noqa: FBT003
        mock.patch("library.mediadb.block.shell_utils.gen_paths", return_value=["https://example.com/new.mp4"]),
        mock.patch(
            "library.mediadb.block.tube_backend.get_video_metadata",
            return_value={"path": "https://example.com/real.mp4"},
        ),
        mock.patch("library.mediadb.block.devices.confirm", return_value=True),
    ):
        block.block(["--db", db_path, "https://example.com/new.mp4"])

    rows = list(db["blocklist"].rows)
    assert {"key": "path", "value": "https://example.com/real.mp4"} in rows
