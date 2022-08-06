import os
import sqlite3

from xklb.utils import stop


def sqlite_con(db):
    if not os.path.exists(db):
        print(f"Database file '{db}' does not exist. Create one with lb extract.")
        stop()

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def fetchall_dict(con, *args):
    return [dict(r) for r in con.execute(*args).fetchall()]
