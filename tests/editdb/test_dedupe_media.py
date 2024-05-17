import argparse
import pytest
from tests.utils import connect_db_args
from xklb.lb import library as lb
from xklb.mediadb import db_media

NO_CHANGE = [
    {
        'id': 1,
        'path': 'path1',
        'title': 'title1',
        'duration': 300,
        'artist': 'R. Mutt',
        'album': 'readymade',
        'size': 1_000_000,
        'audio_count': 1,
        'video_count': 0,
    },
    {
        'id': 2,
        'path': 'path2',
        'title': 'title2',
        'duration': 300,
        'artist': 'R. Mutt',
        'album': 'readymade',
        'size': 1_000_000,
        'audio_count': 1,
        'video_count': 0,
    },
    {
        'id': 3,
        'path': 'path3',
        'title': 'title1',
        'duration': 300,
        'artist': 'R. Mutt',
        'album': 'readymade',
        'size': 1_000_000,
        'audio_count': 1,
        'video_count': 0,
    },
]
NO_CHANGE = [db_media.consolidate(d) for d in NO_CHANGE]


@pytest.fixture
def db1(temp_db):
    db1 = temp_db()
    args = connect_db_args(db1)

    data = NO_CHANGE
    args.db['media'].insert_all(data, pk='id')

    return db1


def test_dedupe_no_bk(db1):
    with pytest.raises(argparse.ArgumentError):
        lb(['dedupe-media', db1])


flags = [
    ('--audio', NO_CHANGE),
    ('--extractor-id', NO_CHANGE),
    ('--title', NO_CHANGE),
    ('--same-duration', NO_CHANGE),
]


@pytest.mark.parametrize("flags,expected", flags)
def test_dedupe(db1, flags, expected):
    lb(['dedupe-media', db1, 'media', *flags.split(' ')])

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) == len(expected)
    assert media == expected
