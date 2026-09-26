from library.mediafiles.torrents_dump import aggregate_trackers


def test_aggregate_trackers():
    torrents = [
        ("one.torrent", {"tracker": "tracker.example", "size": 30}),
        ("two.torrent", {"tracker": "tracker.example", "size": 20}),
        ("three.torrent", {"tracker": "other.example", "size": 10}),
    ]

    assert aggregate_trackers(torrents) == [
        {"tracker": "other.example", "count": 1, "size": "10Bytes"},
        {"tracker": "tracker.example", "count": 2, "size": "50Bytes"},
    ]
