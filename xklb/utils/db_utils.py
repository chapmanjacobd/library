import itertools, sqlite3
from collections.abc import Iterable
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, Any

from xklb.utils import consts, iterables, nums, strings
from xklb.utils.log_utils import log

if TYPE_CHECKING:
    from sqlite_utils import Database


def tracer(sql, params) -> None:
    sql = strings.remove_consecutives(dedent(sql), "\n")
    log.info(f"SQL: {sql} - params: {params}")


def connect(args, conn=None, **kwargs):
    from sqlite_utils import Database

    sqlite3.enable_callback_tracebacks(True)  # noqa: FBT003

    class DB(Database):
        def pop(self, sql: str, params: Iterable | dict | None = None, ignore_errors=None) -> Any | None:
            if ignore_errors is None:
                ignore_errors = ["no such table"]
            try:
                curs = self.execute(sql, params)
                data = curs.fetchone()
            except sqlite3.OperationalError as exc:
                if any(e in str(exc) for e in ignore_errors):
                    return None
                raise
            if data is None or len(data) == 0:
                return None
            return data[0]

        def pop_dict(
            self,
            sql: str,
            params: Iterable | dict | None = None,
            ignore_errors=None,
        ) -> dict | None:
            if ignore_errors is None:
                ignore_errors = ["no such table"]
            try:
                dg = self.query(sql, params)
                d = next(dg, None)
            except sqlite3.OperationalError as e:
                if any(ignore_error in str(e) for ignore_error in ignore_errors):
                    return None
                raise
            return d

    if kwargs.get("memory"):
        db = DB(tracer=tracer if args.verbose >= consts.LOG_DEBUG_SQL else None, **kwargs)  # type: ignore
        return db

    db_override = getattr(args, "db", None)
    if db_override and isinstance(db_override, str):
        args.database = db_override

    if conn is None and not Path(args.database).exists() and ":memory:" not in args.database:
        log.error(f"Database file '{args.database}' does not exist. Create one with lb fsadd, tubeadd, or tabsadd.")
        raise SystemExit(1)

    db = DB(conn or args.database, tracer=tracer if args.verbose >= consts.LOG_DEBUG_SQL else None, **kwargs)  # type: ignore
    with db.conn:  # type: ignore
        db.conn.execute("PRAGMA main.cache_size = 8000")  # type: ignore

    db.enable_wal()
    return db


def columns(args, table_name):
    try:
        return args.db[table_name].columns_dict
    except Exception:
        return {}


config = {
    "playlists": {
        "search_columns": ["path", "title"],
        "column_order": ["id", "path", "extractor_key"],
        "ignore_columns": ["extractor_playlist_id"],
    },
    "media": {
        "search_columns": ["path", "title", "mood", "genre", "description", "artist", "album", "category", "frequency"],
        "column_order": ["id", "path", "webpath", "extractor_id"],
        "ignore_columns": ["extractor_id"],
    },
    "history": {"column_order": ["id"]},
    "captions": {"search_columns": ["text"]},
    "reddit_posts": {
        "search_columns": ["title", "selftext"],
        "column_order": ["path"],
    },
    "reddit_comments": {
        "search_columns": ["body"],
    },
    "hn_comment": {
        "search_columns": ["text", "author"],
    },
    "hn_pollopt": {
        "search_columns": ["text", "author"],
    },
    "hn_poll": {
        "search_columns": ["title", "text", "author"],
    },
    "hn_job": {
        "search_columns": ["title", "text", "author", "path"],
    },
    "hn_story": {
        "search_columns": ["title", "text", "author", "path"],
    },
}


def optimize(args) -> None:
    log.info("\nOptimizing database")

    db: Database = args.db

    for table in config:
        if table not in db.table_names():
            continue
        if getattr(args, "force", False):
            try:
                db[table].disable_fts()  # type: ignore
            except Exception as e:
                log.debug(e)

        log.info("Processing table: %s", table)
        table_columns = db[table].columns_dict
        table_config = config.get(table) or {}
        ignore_columns = table_config.get("ignore_columns") or []
        search_columns = table_config.get("search_columns") or []

        fts_columns = [c for c in search_columns if c in table_columns]
        int_columns = [k for k, v in table_columns.items() if v == int and k not in search_columns + ignore_columns]
        str_columns = [k for k, v in table_columns.items() if v == str and k not in search_columns + ignore_columns]
        if "path" in table_columns:
            str_columns = list({*str_columns, "path"})

        optimized_column_order = list(iterables.ordered_set([*int_columns, *(table_config.get("column_order") or [])]))
        compare_order = zip(table_columns, optimized_column_order)
        was_transformed = False
        if not all(x == y for x, y in compare_order):
            log.info("Transforming column order: %s", optimized_column_order)
            db[table].transform(column_order=optimized_column_order)  # type: ignore
            was_transformed = True

        if getattr(args, "force", False):
            indexes = db[table].indexes  # type: ignore
            for index in indexes:
                if index.unique == 1:
                    db.execute(f"REINDEX {index.name}")
                else:
                    db.execute(f"DROP index {index.name}")

        for column in int_columns + str_columns:
            log.info("Creating index: %s", column)
            try:
                db[table].create_index([column], unique=column == "path", if_not_exists=True, analyze=True)  # type: ignore
            except sqlite3.IntegrityError:
                log.warning("%s %s table %s column is not unique", args.database, table, column)
                db[table].create_index([column], if_not_exists=True, analyze=True)  # type: ignore

        if getattr(args, "fts", True) and any(fts_columns):
            if db[table].detect_fts() is None or was_transformed:  # type: ignore
                log.info("Creating fts index: %s", fts_columns)
                db[table].enable_fts(
                    fts_columns,
                    create_triggers=True,
                    replace=True,
                    tokenize="trigram"
                    if sqlite3.sqlite_version_info >= (3, 34, 0)
                    else 'unicode61 "tokenchars=_."',  # https://www.sqlite.org/releaselog/3_34_0.html
                )
            else:
                with db.conn:  # type: ignore
                    log.info("Optimizing fts index: %s", table)
                    db[table].optimize()  # type: ignore

    log.info("Running VACUUM")
    db.vacuum()
    log.info("Running ANALYZE")
    db.analyze()


def linear_interpolation(x, x1, y1, x2, y2):
    y = y1 + ((x - x1) / (x2 - x1)) * (y2 - y1)
    return y


def has_similar_schema(set1, set2):
    len1 = len(set1)
    len2 = len(set2)
    min_len = min(len1, len2)

    if min_len <= 3:
        return set1 == set2
    elif min_len <= 5:
        return set1.issubset(set2) or set2.issubset(set1)
    else:
        threshold = min_len * (nums.linear_interpolation(min_len, [(6, 0.875), (100, 0.3)]) or 0.8)
        if len1 == min_len:
            return len(set1.intersection(set2)) >= threshold
        else:
            return len(set2.intersection(set1)) >= threshold


def most_similar_schema(keys, existing_tables):
    best_match = None
    highest_ratio = 0

    keys = set(keys)
    threshold = nums.linear_interpolation(len(keys), [(3, 0.8), (100, 0.3)]) or 0.73

    for table_name, columns_dict in existing_tables.items():
        existing_keys = set(columns_dict.keys())

        if keys == existing_keys:
            return table_name

        similar_values = len(keys.intersection(existing_keys))
        if not similar_values:
            avg_commonality = 0
        else:
            provided = similar_values / len(keys)
            existing = similar_values / len(existing_keys)
            avg_commonality = (provided + existing) / 2

            if avg_commonality >= threshold and avg_commonality > highest_ratio:
                highest_ratio = avg_commonality
                best_match = table_name
        log.debug("%s %.2f%%", table_name, avg_commonality * 100)

    return best_match


def add_missing_table_names(args, tables):
    if all(d["table_name"] for d in tables):
        return tables

    existing_tables = {table_name: args.db[table_name].columns_dict for table_name in args.db.table_names()}
    table_id_gen = itertools.count(start=1)

    tables = sorted(tables, key=lambda d: len(d["data"]), reverse=True)
    for d in tables:
        if d["table_name"] is None:
            first_dict_keys = d["data"][0].keys()
            existing_candidate = most_similar_schema(first_dict_keys, existing_tables)
            if existing_candidate:
                d["table_name"] = existing_candidate
            else:
                table_name = f"t{next(table_id_gen)}"
                while table_name in existing_tables:
                    table_name = f"t{next(table_id_gen)}"
                d["table_name"] = table_name

    return tables
