from library.__main__ import library as lb
from tests.utils import connect_db_args, links_db, v_db


def test_merge(temp_db):
    db1 = temp_db()
    lb(["merge-dbs", "--pk", "path", links_db, v_db, db1])

    args = connect_db_args(db1)
    assert args.db.pop("SELECT COUNT(*) FROM media") == 14


def test_split(temp_db):
    db1 = temp_db()
    lb(["merge-dbs", "--pk", "path", links_db, v_db, db1, "-t", "media", "--where", 'path like "http%"'])

    args = connect_db_args(db1)
    assert args.db.pop("SELECT COUNT(*) FROM media") == 10
