import os, sqlite3
from typing import Any, Iterable, List, Optional, Union

import sqlite_utils

from xklb.utils import log


class DB(sqlite_utils.Database):
    def pop(self, sql: str, params: Optional[Union[Iterable, dict]] = None, ignore_errors=None) -> Optional[Any]:
        if ignore_errors is None:
            ignore_errors = ["no such table"]
        try:
            curs = self.execute(sql, params)
        except sqlite3.OperationalError as exc:
            if any([e in str(exc) for e in ignore_errors]):
                return None
            raise
        data = curs.fetchone()
        if data is None or len(data) == 0:
            return None
        return data[0]

    def pop_dict(self, sql: str, params: Optional[Union[Iterable, dict]] = None, ignore_errors=None) -> Optional[Any]:
        if ignore_errors is None:
            ignore_errors = ["no such table"]
        try:
            dg = self.query(sql, params)
        except sqlite3.OperationalError as exc:
            if any([e in str(exc) for e in ignore_errors]):
                return None
            raise
        return next(dg, None)


def tracer(sql, params) -> None:
    print("SQL: {} - params: {}".format(sql, params))


def connect(args, conn=None, **kwargs) -> sqlite_utils.Database:
    if not os.path.exists(args.database) and ":memory:" not in args.database:
        log.error(f"Database file '{args.database}' does not exist. Create one with lb fsadd, tubeadd, or tabsadd.")
        raise SystemExit(1)

    db = DB(conn or args.database, tracer=tracer if args.verbose >= 2 else None, **kwargs)  # type: ignore
    db.execute("PRAGMA main.cache_size = 8000")
    return db


def optimize(args) -> None:
    print("\nOptimizing database")
    db: sqlite_utils.Database = args.db
    tables = db.table_names()
    db.enable_wal()

    config = {
        "media": {
            "search_columns": ["path", "title", "tags", "mood", "genre", "description", "artist", "album"],
            "column_order": ["path", "webpath", "id", "ie_key", "playlist_path"],
            "ignore_columns": ["id"],
        },
        "reddit_posts": {
            "search_columns": ["title", "selftext_html"],
        },
        "reddit_comments": {
            "search_columns": ["body"],
        },
    }

    for table in ["media", "playlists", "reddit_posts", "reddit_comments"]:
        if table in tables:
            table_columns = db[table].columns_dict
            table_config = config.get(table) or {}
            ignore_columns = table_config.get("ignore_columns") or []
            search_columns = table_config.get("search_columns") or []

            fts_columns = [c for c in search_columns if c in table_columns]
            int_columns = [k for k, v in table_columns.items() if v == int and k not in search_columns + ignore_columns]
            str_columns = [k for k, v in table_columns.items() if v == str and k not in search_columns + ignore_columns]

            db[table].transform(column_order=[*int_columns, *(table_config.get("column_order") or [])])  # type: ignore

            for column in int_columns + str_columns:
                db[table].create_index([column], if_not_exists=True, analyze=True)  # type: ignore

            if db[table].detect_fts() is None and any(fts_columns):  # type: ignore
                db[table].enable_fts(fts_columns, create_triggers=True)

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
