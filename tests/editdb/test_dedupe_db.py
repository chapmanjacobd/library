import pytest
from tests.utils import connect_db_args
from xklb.lb import library as lb

NO_CHANGE = [
    {'id': 1, 'path': 'path1', 'title': 'title1'},
    {'id': 2, 'path': 'path1', 'title': 'title2'},
    {'id': 3, 'path': 'path2', 'title': 'title1'},
]

PATH_UNIQUE = [
    {'id': 1, 'path': 'path1', 'title': 'title1'},
    {'id': 3, 'path': 'path2', 'title': 'title1'},
]

TITLE_UNIQUE = [
    {'id': 1, 'path': 'path1', 'title': 'title1'},
    {'id': 2, 'path': 'path1', 'title': 'title2'},
]


@pytest.fixture
def db1(temp_db):
    db1 = temp_db()
    args = connect_db_args(db1)

    data = NO_CHANGE
    args.db['media'].insert_all(data, pk='id')

    return db1


def test_dedupe_nothing(db1):
    lb(['dedupe-dbs', db1, 'media', '--bk=path,title'])

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) == 3


def test_dedupe_no_bk(db1):
    with pytest.raises(SystemExit):
        lb(['dedupe-dbs', db1, 'media', '--pk=path'])


flags = [
    ('--bk=path,title', NO_CHANGE),
    ('--bk=path --pk=path', NO_CHANGE),  # TODO: should this be PATH_UNIQUE ?
    ('--bk=title --pk=title', NO_CHANGE),  # TODO: should this be TITLE_UNIQUE ?
    ('--bk=path,title --pk=path', NO_CHANGE),
    ('--bk=path,title --pk=title', NO_CHANGE),
    ('--bk=path,title --pk=path,title', NO_CHANGE),
    ('--bk=path', PATH_UNIQUE),
    ('--bk=path --pk=title', PATH_UNIQUE),
    ('--bk=path --pk=path,title', PATH_UNIQUE),
    ('--bk=title', TITLE_UNIQUE),
    ('--bk=title --pk=path', TITLE_UNIQUE),
    ('--bk=title --pk=path,title', TITLE_UNIQUE),
]  # list(itertools.product(['--bk=path', '', '--bk=title', '--bk=path,title'], ['--pk=path', '', '--pk=title', '--pk=path,title']))


@pytest.mark.parametrize("flags,expected", flags)
def test_dedupe(db1, flags, expected):
    lb(['dedupe-dbs', db1, 'media', *flags.split(' ')])

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) == len(expected)
    assert media == expected
