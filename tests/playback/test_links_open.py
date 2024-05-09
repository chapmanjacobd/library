from unittest import mock

from xklb.lb import library as lb

links_db = "tests/data/links.db"
lb(
    [
        "links-add",
        links_db,
        '-c=p1',
        "--insert-only",
        "https://site0",
        "https://site1",
        "https://site2",
        "https://site3",
        "https://site4",
        "https://site5",
        "https://site6",
        "https://site7",
        "https://site8",
    ],
)


@mock.patch("xklb.playback.links_open.make_souffle")
def test_links_open(mock_souffle):
    lb(["links-open", links_db])
    media = mock_souffle.call_args[0][1]
    assert len(media) == 7

    lb(["links-open", links_db, "-L", "3"])
    media = mock_souffle.call_args[0][1]
    assert len(media) == 3
    assert media == [
        {'path': 'https://site0', 'category': 'p1'},
        {'path': 'https://site1', 'category': 'p1'},
        {'path': 'https://site2', 'category': 'p1'},
    ]
