from types import SimpleNamespace

from library.database.manage import copy_play_counts


class FakeMediaTable:
    columns_dict = {}


class FakeSourceDB:
    def __getitem__(self, key):
        assert key == "media"
        return FakeMediaTable()

    def query(self, _query):
        return [{"path": "/source/song.mp3", "time_played": 10, "playhead": 4, "done": 1}]


def test_copy_play_count_remaps_paths_and_history(monkeypatch):
    calls = []
    monkeypatch.setattr(copy_play_counts.db_utils, "connect", lambda _args: FakeSourceDB())
    monkeypatch.setattr(
        copy_play_counts.db_history,
        "add",
        lambda _args, paths, **kwargs: calls.append((paths, kwargs)),
    )
    args = SimpleNamespace(source_prefix="/source", target_prefix="/target", verbose=0)

    copy_play_counts.copy_play_count(args, "source.db")

    assert calls == [
        (
            ["/target/song.mp3"],
            {"time_played": 10, "playhead": 4, "mark_done": 1},
        )
    ]
