from types import SimpleNamespace

import pytest

from library.database.add import computers_add
from library.database.manage import db_playlists
from library.utils import db_utils


@pytest.mark.parametrize("legacy_config", [{}, {"hostnames": ["host"], "ext": []}])
def test_computer_add_replaces_all_host_snapshots(monkeypatch, legacy_config):
    args = SimpleNamespace(
        database=":memory:",
        verbose=0,
        ignore_mounts=[],
        extractor_config={"hostnames": ["host"]},
    )
    args.db = db_utils.connect(args)
    db_playlists.create(args)
    first_id = db_playlists.add_entry(args, {"path": "host", "extractor_config": legacy_config})
    second_id = db_playlists.add_entry(args, {"path": "host", "extractor_config": {"ignore_mounts": ["/mnt/ignored"]}})
    other_id = db_playlists.add_entry(args, {"path": "other", "extractor_config": {}})
    args.db["media"].insert_all(
        [
            {"playlists_id": first_id, "path": "/mnt/d7", "free": 1000},
            {"playlists_id": first_id, "path": "/mnt/removed", "free": 1000},
            {"playlists_id": second_id, "path": "/mnt/d7", "free": 100},
            {"playlists_id": other_id, "path": "/mnt/d7", "free": 500},
        ],
        pk=["playlists_id", "path"],
    )
    monkeypatch.setattr(
        computers_add,
        "gather_system_info",
        lambda hostname: {
            "node": hostname,
            "disks": [{"path": "/mnt/d7", "free": 20, "total": 2000, "device": "/dev/sda", "fstype": "ext4"}],
        },
    )
    monkeypatch.setattr(computers_add.db_utils, "optimize", lambda _args: None)

    computers_add.computer_add(args, ["host"])
    args.extractor_config = {"hostnames": ["host", "other"], "ignore_mounts": ["/mnt/ignored"]}
    computers_add.computer_add(args, ["host"])

    hosts = list(args.db.query("SELECT id, extractor_config FROM playlists WHERE path = 'host'"))
    assert len(hosts) == 1
    assert hosts[0]["extractor_config"] == "{}"
    assert list(args.db.query("SELECT playlists_id, path, free FROM media ORDER BY free")) == [
        {"playlists_id": hosts[0]["id"], "path": "/mnt/d7", "free": 20},
        {"playlists_id": other_id, "path": "/mnt/d7", "free": 500},
    ]
    assert db_playlists.get_id(args, "other", {}) == other_id


def test_computer_add_keeps_snapshot_when_refresh_fails(monkeypatch):
    args = SimpleNamespace(database=":memory:", verbose=0, ignore_mounts=[], extractor_config={})
    args.db = db_utils.connect(args)
    db_playlists.create(args)
    host_id = db_playlists.add_entry(args, {"path": "host", "extractor_config": {"hostnames": ["host"]}})
    args.db["media"].insert({"playlists_id": host_id, "path": "/mnt/d7", "free": 100})
    monkeypatch.setattr(computers_add.db_utils, "optimize", lambda _args: None)

    def fail_refresh(_hostname):
        raise TimeoutError

    monkeypatch.setattr(computers_add, "gather_system_info", fail_refresh)

    computers_add.computer_add(args, ["host"])

    assert list(args.db.query("SELECT playlists_id, path, free FROM media")) == [
        {"playlists_id": host_id, "path": "/mnt/d7", "free": 100},
    ]
    assert db_playlists.get_id(args, "host", {"hostnames": ["host"]}) == host_id
