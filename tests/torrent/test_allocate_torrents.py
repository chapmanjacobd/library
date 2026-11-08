from types import SimpleNamespace

import pytest

from library.torrent import allocate_torrents
from library.utils import db_utils


@pytest.mark.parametrize("allocated_column", [False, True])
def test_get_disks_uses_latest_host_snapshot(allocated_column):
    args = SimpleNamespace(
        database=":memory:",
        verbose=0,
        min_free_space=50,
        max_io_rate=100,
        hosts=None,
        include_disks=None,
        exclude_disks=None,
    )
    db = db_utils.connect(args)
    db["playlists"].insert_all(
        [
            {"id": 1, "path": "host", "time_modified": 100, "time_created": 10},
            {"id": 2, "path": "host", "time_modified": 200, "time_created": 20},
            {"id": 3, "path": "other", "time_modified": 100, "time_created": 10},
        ],
        pk="id",
    )
    disks = [
        {"playlists_id": 1, "path": "/mnt/d7", "free": 1000},
        {"playlists_id": 1, "path": "/mnt/removed", "free": 1000},
        {"playlists_id": 2, "path": "/mnt/d7", "free": 60 if allocated_column else 40},
        {"playlists_id": 2, "path": "/mnt/d9", "free": 500},
        {"playlists_id": 3, "path": "/mnt/d7", "free": 200},
    ]
    db["media"].insert_all(
        [
            d
            | {"total": 2000, "device_read_5s": 0, "device_write_5s": 0}
            | ({"allocated": 100 if d["playlists_id"] == 2 else 0} if allocated_column else {})
            for d in disks
        ]
    )

    assert allocate_torrents.get_disks(args, db) == [
        {"host": "other", "mountpoint": "/mnt/d7", "free": 200, "total": 2000},
        {"host": "host", "mountpoint": "/mnt/d9", "free": 400 if allocated_column else 500, "total": 2000},
    ]


@pytest.mark.parametrize(
    ("first_modified", "second_modified", "expected_free"),
    [(300, 200, 100), (100, None, 200), (200, 200, 200)],
)
def test_get_disks_snapshot_order(first_modified, second_modified, expected_free):
    args = SimpleNamespace(
        database=":memory:",
        verbose=0,
        min_free_space=50,
        max_io_rate=100,
        hosts=None,
        include_disks=None,
        exclude_disks=None,
    )
    db = db_utils.connect(args)
    db["playlists"].insert_all(
        [
            {"id": 1, "path": "host", "time_modified": first_modified, "time_created": 10},
            {"id": 2, "path": "host", "time_modified": second_modified, "time_created": 200},
        ],
        pk="id",
    )
    db["media"].insert_all(
        [
            {
                "playlists_id": i,
                "path": "/mnt/d7",
                "free": i * 100,
                "total": 1000,
                "device_read_5s": 0,
                "device_write_5s": 0,
            }
            for i in (1, 2)
        ]
    )

    assert allocate_torrents.get_disks(args, db) == [
        {"host": "host", "mountpoint": "/mnt/d7", "free": expected_free, "total": 1000},
    ]
