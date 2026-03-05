from unittest import mock

from library.__main__ import library as lb
from tests.utils import links_db


@mock.patch("library.playback.links_open.make_souffle")
def test_links_open(mock_souffle):
    lb(["links-open", links_db])
    media = mock_souffle.call_args[0][1]
    assert len(media) == 7

    lb(["links-open", links_db, "-L", "3"])
    media = mock_souffle.call_args[0][1]
    assert len(media) == 3
    assert media == [
        {"path": "https://site0", "hostname": "site0", "category": "p1"},
        {"path": "https://site1", "hostname": "site1", "category": "p1"},
        {"path": "https://site2", "hostname": "site2", "category": "p1"},
    ]

@mock.patch("library.playback.links_open.make_souffle")
@mock.patch("library.playback.links_open.play")
def test_links_open_brackets(mock_play, mock_souffle, temp_db):
    db_path = temp_db()
    url = "https://example.com/test?page[]=107"
    lb(["links-add", "--no-extract", db_path, url])
    lb(["links-open", db_path, "-s", url])
    
    assert mock_souffle.called
    media = mock_souffle.call_args[0][1]
    assert len(media) == 1
    assert media[0]["path"] == url
