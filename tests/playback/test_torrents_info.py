from types import SimpleNamespace

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
