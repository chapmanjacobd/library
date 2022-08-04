import os
import sqlite3

from xklb.utils import stop


def sqlite_con(db):
    if not os.path.exists(db):
        print('Database file does not exist. Create one first with lb-extract.')
        stop()

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def fetchall_dict(con, *args):
    return [dict(r) for r in con.execute(*args).fetchall()]
