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
