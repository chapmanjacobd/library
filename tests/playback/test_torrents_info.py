from types import SimpleNamespace

import pytest

from library.playback import torrents_info


class Arguments(SimpleNamespace):
    def __contains__(self, option):
        return option != "avg_sizes"

    def __getattr__(self, _name):
        return None


def test_avg_sizes_treats_zero_file_torrent_as_zero(monkeypatch):
    torrent = object()
    average_sizes = []
    args = Arguments(
        defaults=Arguments(),
        avg_sizes=lambda size: average_sizes.append(size) or True,
    )
    monkeypatch.setattr(torrents_info, "torrent_files", lambda _torrent: [])

    assert torrents_info.filter_torrents_by_criteria(args, [torrent]) == [torrent]
    assert average_sizes == [0]


def test_set_torrent_paths_updates_save_and_temp_paths():
    calls = []

    class QBitTorrent:
        def torrents_set_location(self, path, torrent_hashes):
            calls.append(("save", path, torrent_hashes))

        def torrents_set_download_path(self, path, torrent_hashes):
            calls.append(("temp", path, torrent_hashes))

    torrent = SimpleNamespace(hash="abc", save_path="/old/save", download_path="/old/temp")

    torrents_info.set_torrent_paths(QBitTorrent(), torrent, "/new/temp", "/new/save")

    assert calls == [
        ("save", "/new/save", ["abc"]),
        ("temp", "/new/temp", ["abc"]),
    ]


def test_set_torrent_paths_preserves_save_path_when_only_temp_path_changes():
    calls = []

    class QBitTorrent:
        def torrents_set_location(self, path, torrent_hashes):
            calls.append(("save", path, torrent_hashes))

        def torrents_set_download_path(self, path, torrent_hashes):
            calls.append(("temp", path, torrent_hashes))

    torrent = SimpleNamespace(hash="abc", save_path="/old/save", download_path="/old/temp")

    torrents_info.set_torrent_paths(QBitTorrent(), torrent, "/new/temp", None)

    assert calls == [
        ("save", "/old/save", ["abc"]),
        ("temp", "/new/temp", ["abc"]),
    ]


@pytest.mark.parametrize(
    ("path_search", "expected"),
    [
        ("status", ["/old/temp"]),
        ("download", ["/old/temp"]),
        ("save", ["/old/save"]),
        ("both", ["/old/temp", "/old/save"]),
    ],
)
def test_torrent_paths_for_search(path_search, expected):
    torrent = SimpleNamespace(
        save_path="/old/save",
        download_path="/old/temp",
        state_enum=SimpleNamespace(is_complete=False),
    )
    args = SimpleNamespace(path_search=path_search)

    assert torrents_info.torrent_paths_for_search(args, torrent) == expected


@pytest.mark.parametrize(
    ("different_drives", "expected"),
    [
        (None, ["/old/temp"]),
        (True, ["/old/temp", "/old/save"]),
        (False, ["/old/temp", "/old/save"]),
    ],
)
def test_torrent_paths_for_search_defaults_to_status_or_both(different_drives, expected):
    torrent = SimpleNamespace(
        save_path="/old/save",
        download_path="/old/temp",
        state_enum=SimpleNamespace(is_complete=False),
    )
    args = SimpleNamespace(different_drives=different_drives)

    assert torrents_info.torrent_paths_for_search(args, torrent) == expected


@pytest.mark.parametrize(
    ("path_search", "query", "expected"),
    [
        ("status", "/mnt/d4", ["incomplete", "complete"]),
        ("download", "/mnt/d4", ["incomplete"]),
        ("save", "/mnt/d5", ["incomplete"]),
        ("both", "/mnt/d5", ["incomplete", "complete"]),
    ],
)
def test_filter_torrents_by_criteria_searches_selected_path(monkeypatch, path_search, query, expected):
    monkeypatch.setattr(torrents_info, "torrent_files", lambda _torrent: [])
    torrents = [
        SimpleNamespace(
            name="incomplete",
            comment="",
            hash="abc",
            save_path="/mnt/d5/seeding",
            download_path="/mnt/d4/downloading",
            state_enum=SimpleNamespace(is_complete=False),
        ),
        SimpleNamespace(
            name="complete",
            comment="",
            hash="def",
            save_path="/mnt/d4/seeding",
            download_path="/mnt/d5/downloading",
            state_enum=SimpleNamespace(is_complete=True),
        ),
    ]
    args = Arguments(
        defaults=Arguments(),
        avg_sizes=lambda _size: True,
        path_search=path_search,
        torrent_search=[query],
    )

    assert [t.name for t in torrents_info.filter_torrents_by_criteria(args, torrents)] == expected


def test_torrent_paths_on_different_drives(monkeypatch):
    torrent = SimpleNamespace(download_path="/mnt/d4/downloading", save_path="/mnt/d5/seeding")
    mountpoints = {
        "/mnt/d4/downloading": "/mnt/d4",
        "/mnt/d5/seeding": "/mnt/d5",
    }
    monkeypatch.setattr(torrents_info.path_utils, "mountpoint", mountpoints.__getitem__)

    assert torrents_info.torrent_paths_on_different_drives(torrent)


def test_filter_torrents_by_criteria_can_select_different_drives(monkeypatch):
    monkeypatch.setattr(torrents_info, "torrent_files", lambda _torrent: [])
    monkeypatch.setattr(
        torrents_info.path_utils,
        "mountpoint",
        lambda path: "/mnt/d4" if path.startswith("/mnt/d4") else "/mnt/d5",
    )
    torrents = [
        SimpleNamespace(
            name="different",
            comment="",
            hash="abc",
            save_path="/mnt/d5/seeding",
            download_path="/mnt/d4/downloading",
            state_enum=SimpleNamespace(is_complete=False),
        ),
        SimpleNamespace(
            name="same",
            comment="",
            hash="def",
            save_path="/mnt/d4/seeding",
            download_path="/mnt/d4/downloading",
            state_enum=SimpleNamespace(is_complete=False),
        ),
    ]
    args = Arguments(defaults=Arguments(), avg_sizes=lambda _size: True, different_drives=True)

    assert [t.name for t in torrents_info.filter_torrents_by_criteria(args, torrents)] == ["different"]


def test_filter_torrents_by_criteria_can_select_same_drives(monkeypatch):
    monkeypatch.setattr(torrents_info, "torrent_files", lambda _torrent: [])
    monkeypatch.setattr(
        torrents_info.path_utils,
        "mountpoint",
        lambda path: "/mnt/d4" if path.startswith("/mnt/d4") else "/mnt/d5",
    )
    torrents = [
        SimpleNamespace(
            name="different",
            comment="",
            hash="abc",
            save_path="/mnt/d5/seeding",
            download_path="/mnt/d4/downloading",
            state_enum=SimpleNamespace(is_complete=False),
        ),
        SimpleNamespace(
            name="same",
            comment="",
            hash="def",
            save_path="/mnt/d4/seeding",
            download_path="/mnt/d4/downloading",
            state_enum=SimpleNamespace(is_complete=False),
        ),
    ]
    args = Arguments(defaults=Arguments(), avg_sizes=lambda _size: True, different_drives=False)

    assert [t.name for t in torrents_info.filter_torrents_by_criteria(args, torrents)] == ["same"]
