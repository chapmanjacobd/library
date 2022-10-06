import os, sqlite3
from typing import Any, List, Optional

import sqlite_utils

from xklb.utils import log


class DB(sqlite_utils.Database):
    def pop(self: sqlite_utils.Database, query: str) -> Optional[Any]:
        try:
            curs = self.execute(query)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return None
            raise
        return curs.fetchone()[0]


def tracer(sql, params) -> None:
    print("SQL: {} - params: {}".format(sql, params))


def connect(args) -> sqlite_utils.Database:
    if not os.path.exists(args.database) and ":memory:" not in args.database:
        log.error(f"Database file '{args.database}' does not exist. Create one with lb fsadd, tubeadd, or tabsadd.")
        exit(1)

    db = DB(args.database, tracer=tracer if args.verbose >= 2 else None)  # type: ignore
    db.execute("PRAGMA main.cache_size = 8000")
    return db


def optimize(args) -> None:
    print("\nOptimizing database")
    db: sqlite_utils.Database = args.db
    tables = db.table_names()
    db.enable_wal()

    config = {
        "media": {
            "fts_able_columns": ["path", "title", "tags", "mood", "genre", "description", "artist", "album"],
            "column_order": ["path", "webpath", "id", "ie_key", "playlist_path"],
            "ignore_columns": ["id"],
        },
        "reddit_posts": {
            "fts_able_columns": ["title", "selftext"],
        },
        "reddit_comments": {
            "fts_able_columns": ["body"],
        },
    }

    for table in ["media", "playlists", "subreddits", "reddit_posts", "reddit_comments"]:
        if table in tables:
            table_columns = db[table].columns_dict
            table_config = config.get(table) or {}
            ignore_columns = table_config.get("ignore_columns") or []
            fts_able_columns = table_config.get("fts_able_columns") or []

            fts_columns = [c for c in fts_able_columns if c in table_columns]
            int_columns = [
                k for k, v in table_columns.items() if v == int and k not in fts_able_columns + ignore_columns
            ]
            str_columns = [
                k for k, v in table_columns.items() if v == str and k not in fts_able_columns + ignore_columns
            ]

            for column in int_columns + str_columns + ["path"]:
                db[table].create_index([column], if_not_exists=True, analyze=True)  # type: ignore

            if db[table].detect_fts() is None and any(fts_columns):  # type: ignore
                db[table].enable_fts(fts_columns, create_triggers=True)

            db[table].transform(column_order=[*int_columns, *(table_config.get("column_order") or [])])  # type: ignore
            with db.conn:
                db[table].optimize()  # type: ignore

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


def gen_include_excludes(cols_available):
    searchable_columns = [
        "path",
        "title",
        "mood",
        "genre",
        "year",
        "bpm",
        "key",
        "time",
        "decade",
        "categories",
        "city",
        "country",
        "description",
        "album",
        "artist",
        "tags",
        "playlist_path",
    ]

    valid_cols = [f"media.{c}" for c in searchable_columns if c in cols_available]

    include_string = "and (" + " like :include{} OR ".join(valid_cols) + " like :include{} )"
    exclude_string = "and (" + " not like :exclude{} AND ".join(valid_cols) + " not like :exclude{} )"

    return include_string, exclude_string
