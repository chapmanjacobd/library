import os
from typing import List

import sqlite_utils

from xklb.utils import log


def tracer(sql, params) -> None:
    print("SQL: {} - params: {}".format(sql, params))


def connect(args) -> sqlite_utils.Database:
    if not os.path.exists(args.database) and ":memory:" not in args.database:
        log.error(f"Database file '{args.database}' does not exist. Create one with lb fsadd, tubeadd, or tabsadd.")
        exit(1)

    return sqlite_utils.Database(args.database, tracer=tracer if args.verbose >= 2 else None)  # type: ignore


def optimize(args) -> None:
    print("Optimizing database")
    db: sqlite_utils.Database = args.db
    columns = db["media"].columns_dict

    ignore_columns = ["id"]
    fts_able_columns = ["path", "title", "tags", "mood", "genre", "description", "artist", "album"]
    fts_columns = [c for c in fts_able_columns if c in columns]
    int_columns = [k for k, v in columns.items() if v == int and k not in fts_able_columns + ignore_columns]
    str_columns = [k for k, v in columns.items() if v == str and k not in fts_able_columns + ignore_columns]

    for column in int_columns + str_columns:
        db["media"].create_index([column], if_not_exists=True, analyze=True)  # type: ignore

    if db["media"].detect_fts() is None and any(fts_columns):  # type: ignore
        db["media"].enable_fts(fts_columns, create_triggers=True)

    db.enable_wal()
    #
    # sqlite-utils optimize
    #
    with db.conn:
        db["media"].optimize()  # type: ignore
    db.vacuum()
    db.analyze()


def fts_quote(query: List[str]) -> List[str]:
    fts_words = [" NOT ", " AND ", " OR ", "*", ":", "NEAR("]
    return [s if any([r in s for r in fts_words]) else '"' + s + '"' for s in query]


def fts_search(args, bindings) -> str:
    bindings["query"] = " AND ".join(fts_quote(args.include))
    if args.exclude:
        bindings["query"] += " NOT " + " NOT ".join(fts_quote(args.exclude))
    table = "(" + args.db["media"].search_sql() + ")"  #  include_rank=True
    return table
