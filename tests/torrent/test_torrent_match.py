import hashlib
from types import SimpleNamespace
from pathlib import Path

import pytest

from library.torrent import torrent_match
from library.torrent import torrents_start
from library.torrent.torrent_match import TorrentFile, contained_piece_spans, match_file


class FakeStorage:
    def __init__(self, path, size, offset):
        self.path = path
        self.size = size
        self.offset = offset

    def file_path(self, _index):
        return self.path

    def file_size(self, _index):
        return self.size

    def file_offset(self, _index):
        return self.offset


class FakeTorrent:
    def __init__(self, data, piece_length):
        self.data = data
        self._piece_length = piece_length
        self.storage = FakeStorage("video.mkv", len(data), 0)

    def name(self):
        return "video"

    def files(self):
        return self.storage

    def piece_length(self):
        return self._piece_length

    def total_size(self):
        return len(self.data)

    def hash_for_piece(self, index):
        start = index * self._piece_length
        return hashlib.sha1(self.data[start : start + self._piece_length]).digest()


def test_contained_piece_spans_skip_partial_boundary_pieces():
    file = TorrentFile(object(), "torrent", "part", 4, 3, 0)

    assert list(contained_piece_spans(file, piece_length=4, total_size=10)) == []


def test_match_file_checks_each_wholly_contained_piece(tmp_path: Path):
    data = b"abcdefgh"
    path = tmp_path / "video.mkv"
    path.write_bytes(data)
    torrent = FakeTorrent(data, piece_length=4)
    file = TorrentFile(torrent, "video", "video.mkv", len(data), 0, 0)

    assert match_file(path, file, min_pieces=2) == {
        "candidate": str(path),
        "torrent": "video",
        "torrent_file": "video.mkv",
        "matches": 2,
        "pieces": 2,
        "percent": 100.0,
        "matched_bytes": 8,
        "checked_bytes": 8,
        "unchecked_bytes": 0,
    }


def test_derive_save_path_rejects_unsafe_torrent_paths(tmp_path: Path):
    candidate = tmp_path / "library" / "video.mkv"

    assert torrent_match.derive_save_path(candidate, "video.mkv") == tmp_path / "library"
    with pytest.raises(ValueError, match="Unsafe"):
        torrent_match.derive_save_path(candidate, "../video.mkv")


def test_add_matches_to_qbittorrent_is_confirmed_paused_and_hash_checks(monkeypatch, tmp_path: Path):
    torrent_path = tmp_path / "video.torrent"
    candidate = tmp_path / "library" / "video.mkv"
    matches = [
        {
            "torrent_path": str(torrent_path),
            "candidate": str(candidate),
            "torrent_file": "video.mkv",
        }
    ]
    calls = []

    class FakeQBit:
        def torrents_add(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("library.utils.devices.confirm", lambda _message: True)
    monkeypatch.setattr(torrents_start, "start_qBittorrent", lambda _args: FakeQBit())
    args = SimpleNamespace(start=False, skip_checking=False)

    torrent_match.add_matches_to_qbittorrent(matches, args)

    assert calls == [
        {
            "torrent_files": torrent_path,
            "download_path": str(tmp_path / "library"),
            "save_path": str(tmp_path / "library"),
            "use_auto_torrent_management": False,
            "is_paused": True,
            "is_stopped": True,
            "add_to_top_of_queue": False,
        }
    ]
