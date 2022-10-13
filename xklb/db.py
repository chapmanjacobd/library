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
            data = curs.fetchone()
        except sqlite3.OperationalError as exc:
            if any([e in str(exc) for e in ignore_errors]):
                return None
            raise
        if data is None or len(data) == 0:
            return None
        return data[0]

    def pop_dict(self, sql: str, params: Optional[Union[Iterable, dict]] = None, ignore_errors=None) -> Optional[Any]:
        if ignore_errors is None:
            ignore_errors = ["no such table"]
        try:
            dg = self.query(sql, params)
            d = next(dg, None)
        except sqlite3.OperationalError as exc:
            if any([e in str(exc) for e in ignore_errors]):
                return None
            raise exc
        return d


def tracer(sql, params) -> None:
    print("SQL: {} - params: {}".format(sql, params))


def connect(args, conn=None, **kwargs) -> sqlite_utils.Database:
    if not os.path.exists(args.database) and ":memory:" not in args.database:
        log.error(f"Database file '{args.database}' does not exist. Create one with lb fsadd, tubeadd, or tabsadd.")
        raise SystemExit(1)

    db = DB(conn or args.database, tracer=tracer if args.verbose >= 2 else None, **kwargs)  # type: ignore
    with db.conn:
        db.conn.execute("PRAGMA main.cache_size = 8000")
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

            optimized_column_order = [*int_columns, *(table_config.get("column_order") or [])]
            current_order = zip(table_columns, optimized_column_order)
            was_transformed = False
            if not all([x == y for x, y in current_order]):
                db[table].transform(column_order=optimized_column_order)  # type: ignore
                was_transformed = True

            for column in int_columns + str_columns:
                db[table].create_index([column], if_not_exists=True, analyze=True)  # type: ignore

            if any(fts_columns) and (db[table].detect_fts() is None or was_transformed):  # type: ignore
                db[table].enable_fts(fts_columns, create_triggers=True, replace=True)

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


def get_playlists(args, cols="path, dl_config", constrain=False, sql_filters=None) -> List[dict]:
    columns = args.db["playlists"].columns_dict
    if sql_filters is None:
        sql_filters = []
    if "time_deleted" in columns:
        sql_filters.append("AND time_deleted=0")
    if constrain:
        if args.category:
            sql_filters.append(f"AND category='{args.category}'")

    try:
        known_playlists = list(
            args.db.query(f"select {cols} from playlists where 1=1 {' '.join(sql_filters)} order by random()")
        )
    except sqlite3.OperationalError:
        known_playlists = []
    return known_playlists


def get_playlists_join(args):
    media_columns = args.db["media"].columns_dict
    if "ie_key" in media_columns:
        join = "(p.ie_key = media.ie_key = 'Local' and media.path like p.path || '%' ) "
        if "playlist_path" in media_columns:
            join += "or (p.ie_key = media.ie_key and media.ie_key != 'Local' and p.path = media.playlist_path)"
    else:
        join = "p.path = media.playlist_path"

    return join
