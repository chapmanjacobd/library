import os

import sqlite_utils

from xklb.utils import log


def tracer(sql, params):
    print("SQL: {} - params: {}".format(sql, params))


def connect_db(args):
    if not os.path.exists(args.database) and ":memory:" not in args.database:
        log.error(
            f"Database file '{args.database}' does not exist. Create one with lb extract / lb tubeadd / lb tabsadd."
        )
        exit(1)

    return sqlite_utils.Database(args.database, tracer=tracer if args.verbose > 1 else None)  # type: ignore


def fetchall_dict(con, *args):
    return [dict(r) for r in con.execute(*args).fetchall()]


def optimize_db(args):
    print("Optimizing database")
    db: sqlite_utils.Database = args.db
    columns = db["media"].columns_dict

    ignore_columns = ["id"]
    fts_columns = ["path", "title", "tags", "mood", "genre", "description", "artist", "album"]
    int_columns = [k for k, v in columns.items() if v == int and k not in fts_columns + ignore_columns]
    str_columns = [k for k, v in columns.items() if v == str and k not in fts_columns + ignore_columns]

    for column in int_columns + str_columns:
        db["media"].create_index([column], if_not_exists=True, analyze=True)  # type: ignore

    if db["media"].detect_fts() is None:  # type: ignore
        db["media"].enable_fts([c for c in fts_columns if c in columns], create_triggers=True)

    #
    # sqlite-utils optimize
    #
    with db.conn:
        db["media"].optimize()  # type: ignore
    db.vacuum()
