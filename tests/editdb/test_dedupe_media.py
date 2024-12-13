import argparse

import pytest

from library.__main__ import library as lb
from tests.utils import connect_db_args

NO_CHANGE = [
    {
        "id": 1,
        "path": "https://path1",
        "size": 1000000,
        "duration": 300,
        "time_created": 1715928751,
        "time_modified": 0,
        "time_deleted": 0,
        "time_downloaded": 0,
        "title": "title1",
        "extractor_id": "1",
        "artist": "Ooo",
    },
    {
        "id": 4,
        "path": "/path1",
        "size": 1000000,
        "duration": 300,
        "time_created": 1715928751,
        "time_modified": 0,
        "time_deleted": 0,
        "time_downloaded": 0,
        "title": "title1",
        "extractor_id": "4",
        "artist": "Moo",
    },
    {
        "id": 2,
        "path": "/path2",
        "size": 1000000,
        "duration": 300,
        "time_created": 1715928751,
        "time_modified": 0,
        "time_deleted": 0,
        "time_downloaded": 0,
        "title": "title2",
        "extractor_id": "1",
    },
    {
        "id": 3,
        "path": "/path3",
        "size": 1000000,
        "duration": 300,
        "time_created": 1715928751,
        "time_modified": 0,
        "time_deleted": 0,
        "time_downloaded": 0,
        "title": "title1",
        "extractor_id": "2",
        "artist": "Moo",
    },
]


@pytest.fixture
def db1(temp_db):
    db1 = temp_db()
    args = connect_db_args(db1)

    data = NO_CHANGE
    args.db["media"].insert_all(data, pk="id")

    return db1


def test_dedupe_no_bk(db1):
    with pytest.raises(argparse.ArgumentError):
        lb(["dedupe-media", db1])


flags = [
    ("--audio", ["/path3"]),
    ("--extractor-id", ["https://path1"]),
    ("--same-duration", ["https://path1", "/path2", "/path3"]),
    ("--title", ["https://path1", "/path3"]),
    ("--title --compare-dirs / http", ["https://path1"]),
]


@pytest.mark.parametrize(("flags", "deleted"), flags)
def test_dedupe(db1, flags, deleted):
    lb(["dedupe-media", db1, *flags.split(" ")])

    args = connect_db_args(db1)
    media = list(d["path"] for d in args.db.query("SELECT path FROM media WHERE time_deleted>0"))

    assert media == deleted
