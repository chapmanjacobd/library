from tests.utils import connect_db_args, tube_db, v_db
from xklb.lb import library as lb


def test_merge(temp_db):
    db1 = temp_db()
    lb(["merge-dbs", "--pk", "path", tube_db, v_db,  db1])

    args = connect_db_args(db1)
    assert args.db.pop("SELECT COUNT(*) FROM media") == 6


def test_split(temp_db):
    db1 = temp_db()
    lb(["merge-dbs", "--pk", "path", tube_db, v_db,  db1, "-t", "media", "--where", 'path like "http%"'])

    args = connect_db_args(db1)
    assert args.db.pop("SELECT COUNT(*) FROM media") == 2
