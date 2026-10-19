import sqlite3
from types import SimpleNamespace

from sqlite_utils import Database

from library.__main__ import library as lb
from library.database.manage import merge_dbs
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


def test_merge_integrity_error_does_not_become_stop_iteration(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE t (value INTEGER)")
        conn.execute("INSERT INTO t VALUES (-1)")
    with sqlite3.connect(target) as conn:
        conn.execute("CREATE TABLE t (value INTEGER CHECK (value > 0))")

    args = SimpleNamespace(
        db=Database(target),
        only_tables=None,
        skip_columns=None,
        primary_keys=None,
        business_keys=None,
        only_target_columns=False,
        where=None,
        ignore=False,
        upsert=False,
        verbose=0,
    )
    monkeypatch.setattr(
        merge_dbs.db_utils,
        "connect",
        lambda _args, conn: Database(conn),
    )

    merge_dbs.merge_db(args, str(source))
