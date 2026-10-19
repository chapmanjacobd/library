from types import SimpleNamespace

from library.download.redownload import list_deletions


class FakeDB:
    def query(self, _query, params):
        assert params == ["2"]
        return [
            {"time_deleted": "2024-01-02T00:00:00", "count": 2},
            {"time_deleted": "2024-01-01T00:00:00", "count": 1},
        ]


def test_list_deletions_returns_oldest_first():
    args = SimpleNamespace(db=FakeDB(), limit="2")

    assert list_deletions(args) == [
        {"time_deleted": "2024-01-01T00:00:00", "count": 1},
        {"time_deleted": "2024-01-02T00:00:00", "count": 2},
    ]
