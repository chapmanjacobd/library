import sqlite3
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Union

from xklb import consts, utils
from xklb.utils import log

if TYPE_CHECKING:
    from sqlite_utils import Database


def tracer(sql, params) -> None:
    sql = utils.remove_consecutives(dedent(sql), "\n")
    log.info(f"SQL: {sql} - params: {params}")


def connect(args, conn=None, **kwargs):
    from sqlite_utils import Database

    sqlite3.enable_callback_tracebacks(True)  # noqa: FBT003

    class DB(Database):
        def pop(self, sql: str, params: Optional[Union[Iterable, dict]] = None, ignore_errors=None) -> Optional[Any]:
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
            params: Optional[Union[Iterable, dict]] = None,
            ignore_errors=None,
        ) -> Optional[Dict]:
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
        db = DB(tracer=tracer if args.verbose >= consts.LOG_DEBUG else None, **kwargs)  # type: ignore
        return db

    if not Path(args.database).exists() and ":memory:" not in args.database:
        log.error(f"Database file '{args.database}' does not exist. Create one with lb fsadd, tubeadd, or tabsadd.")
        raise SystemExit(1)

    db = DB(conn or args.database, tracer=tracer if args.verbose >= 2 else None, **kwargs)  # type: ignore
    with db.conn:
        db.conn.execute("PRAGMA main.cache_size = 8000")

    db.enable_wal()
    return db


def optimize(args) -> None:
    if not hasattr(args, "force"):
        args.force = False

    log.info("\nOptimizing database")

    db: Database = args.db

    config = {
        "media": {
            "search_columns": ["path", "title", "tags", "mood", "genre", "description", "artist", "album"],
            "column_order": ["path", "webpath", "id", "ie_key", "playlist_path"],
            "ignore_columns": ["id"],
        },
        "reddit_posts": {
            "search_columns": ["title", "selftext"],
            "column_order": ["playlist_path", "path"],
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
        "playlists": {
            "column_order": ["path", "ie_key"],
        },
    }

    for table in config:
        if table not in db.table_names():
            continue
        if args.force:
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

        optimized_column_order = [*int_columns, *(table_config.get("column_order") or [])]
        compare_order = zip(table_columns, optimized_column_order)
        was_transformed = False
        if not all(x == y for x, y in compare_order):
            log.info("Transforming column order: %s", optimized_column_order)
            db[table].transform(column_order=optimized_column_order)  # type: ignore
            was_transformed = True

        if args.force:
            indexes = db[table].indexes  # type: ignore
            for index in indexes:
                if index.unique == 1:
                    db.execute(f"REINDEX {index.name}")
                else:
                    db.execute(f"DROP index {index.name}")

        for column in int_columns + str_columns:
            log.info("Creating index: %s", column)
            db[table].create_index([column], if_not_exists=True, analyze=True)  # type: ignore

        if any(fts_columns) and (db[table].detect_fts() is None or was_transformed):  # type: ignore
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
            with db.conn:
                log.info("Optimizing fts index: %s", table)
                db[table].optimize()  # type: ignore

    log.info("Running VACUUM")
    db.vacuum()
    log.info("Running ANALYZE")
    db.analyze()


def fts_quote(query: List[str]) -> List[str]:
    fts_words = [" NOT ", " AND ", " OR ", "*", ":", "NEAR("]
    return [s if any(r in s for r in fts_words) else '"' + s + '"' for s in query]


def fts_search(args) -> str:
    args.filter_bindings["query"] = " AND ".join(fts_quote(args.include))
    if args.exclude:
        args.filter_bindings["query"] += " NOT " + " NOT ".join(fts_quote(args.exclude))
    table = "(" + args.db["media"].search_sql(include_rank=True) + ")"
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

    valid_cols = [f"m.{c}" for c in searchable_columns if c in cols_available]

    incl = ":include{0}"
    excl = ":exclude{0}"
    include_string = "AND (" + " OR ".join([f"{col} LIKE {incl}" for col in valid_cols]) + ")"
    exclude_string = "AND (" + " AND ".join([f"COALESCE({col},'') NOT LIKE {excl}" for col in valid_cols]) + ")"

    return include_string, exclude_string


def get_playlists(args, cols="path, dl_config", constrain=False, sql_filters=None) -> List[dict]:
    columns = args.db["playlists"].columns_dict
    if sql_filters is None:
        sql_filters = []
    if "time_deleted" in columns:
        sql_filters.append("AND COALESCE(time_deleted,0) = 0")
    if constrain and args.category:
        sql_filters.append(f"AND category='{args.category}'")

    try:
        known_playlists = list(
            args.db.query(f"select {cols} from playlists where 1=1 {' '.join(sql_filters)} order by random()"),
        )
    except sqlite3.OperationalError:
        known_playlists = []
    return known_playlists
