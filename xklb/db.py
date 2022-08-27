import os, sqlite3
from pathlib import Path

from xklb.utils import cmd, log, single_column_tolist


def sqlite_con(db):
    if not os.path.exists(db) and ":memory:" not in db:
        log.error(f"Database file '{db}' does not exist. Create one with lb extract / lb tubeadd / lb tabsadd.")
        exit(1)

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def fetchall_dict(con, *args):
    return [dict(r) for r in con.execute(*args).fetchall()]


def optimize_db(args):
    def get_columns(args):
        try:
            query = "SELECT name FROM PRAGMA_TABLE_INFO('media') where type in ('TEXT', 'INTEGER');"
            cols = single_column_tolist(args.con.execute(query).fetchall(), "name")
        except sqlite3.OperationalError:
            cols = []
        return cols

    if args.optimize:
        print("Optimizing database")
        if Path(args.database).exists():
            cmd("sqlite-utils", "optimize", args.database)
            columns = get_columns(args)

            for column in columns:
                cmd("sqlite-utils", "create-index", "--if-not-exists", "--analyze", args.database, "media", column)
