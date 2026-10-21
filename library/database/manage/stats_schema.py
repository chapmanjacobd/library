"""Report SQLite schema objects and their read-only storage statistics."""

import argparse
import sqlite3

from library.database.manage._readonly import (
    connect_readonly,
    quote_identifier,
    table_info,
    table_names,
    validate_identifier,
)
from library.utils import argparse_utils, printing


SCHEMA_KINDS = ("table", "column", "index")


def _storage_stats(connection: sqlite3.Connection, *, enabled: bool = True) -> tuple[dict[str, dict[str, int]], str]:
    if not enabled:
        return {}, "fallback (PRAGMA page_count/page_size)"
    try:
        rows = connection.execute(
            "SELECT name, COUNT(*) AS pages, COALESCE(SUM(pgsize), 0) AS bytes FROM dbstat GROUP BY name"
        )
        return {row["name"]: {"pages": row["pages"], "bytes": row["bytes"]} for row in rows}, "dbstat"
    except sqlite3.OperationalError:
        return {}, "fallback (PRAGMA page_count/page_size)"


def schema_report(
    database: str,
    *,
    table: str | None = None,
    kind: str | None = None,
    use_dbstat: bool = True,
) -> list[dict]:
    if table is not None:
        validate_identifier(table, label="table name")
    if kind is not None and kind not in SCHEMA_KINDS:
        message = f"invalid schema kind: {kind!r}"
        raise ValueError(message)
    connection = connect_readonly(database)
    try:
        names = table_names(connection, table)
        storage, source = _storage_stats(connection, enabled=use_dbstat)
        fallback_pages = connection.execute("PRAGMA page_count").fetchone()[0]
        fallback_bytes = fallback_pages * connection.execute("PRAGMA page_size").fetchone()[0]
        report = []
        for name in names:
            quoted_name = quote_identifier(name, label="table name")
            schema_row = connection.execute("SELECT type, sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
            details = storage.get(name, {"pages": fallback_pages, "bytes": fallback_bytes})
            if kind in (None, "table"):
                report.append(
                    {
                        "kind": "table",
                        "schema": "main",
                        "table": name,
                        "name": name,
                        "type": schema_row["type"],
                        "columns": None,
                        "details": schema_row["sql"],
                        "rows": connection.execute(f"SELECT COUNT(*) FROM {quoted_name}").fetchone()[0],  # noqa: S608 - table is validated
                        "pages": details["pages"],
                        "bytes": details["bytes"],
                        "stats_source": source,
                    }
                )
            if kind in (None, "column"):
                for column in table_info(connection, name):
                    report.append(  # noqa: PERF401 - rows have a stable schema shared by all report kinds
                        {
                            "kind": "column",
                            "schema": "main",
                            "table": name,
                            "name": column["name"],
                            "type": column["type"],
                            "columns": None,
                            "details": f"pk={column['pk']} notnull={column['notnull']} default={column['dflt_value']}",
                            "rows": None,
                            "pages": None,
                            "bytes": None,
                            "stats_source": source,
                        }
                    )
            if kind in (None, "index"):
                for index in connection.execute(f"PRAGMA index_list({quoted_name})"):
                    index_name = index["name"]
                    index_columns = [
                        row["name"] for row in connection.execute(f"PRAGMA index_info({quote_identifier(index_name)})")
                    ]
                    index_details = storage.get(index_name, {"pages": fallback_pages, "bytes": fallback_bytes})
                    report.append(
                        {
                            "kind": "index",
                            "schema": "main",
                            "table": name,
                            "name": index_name,
                            "type": "unique" if index["unique"] else "index",
                            "columns": ", ".join(index_columns),
                            "details": f"origin={index['origin']} partial={index['partial']}",
                            "rows": None,
                            "pages": index_details["pages"],
                            "bytes": index_details["bytes"],
                            "stats_source": source,
                        }
                    )
        return report
    finally:
        connection.close()


def schema_stats(
    database: str,
    *,
    table: str | None = None,
    kind: str | None = None,
    use_dbstat: bool = True,
) -> list[dict]:
    return schema_report(database, table=table, kind=kind, use_dbstat=use_dbstat)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--db", dest="database_override", metavar="DATABASE")
    parser.add_argument("--table")
    parser.add_argument("--kind", choices=SCHEMA_KINDS, help="filter results by schema object kind")
    parser.add_argument("--no-dbstat", action="store_true")
    args = parser.parse_args(argv)
    if args.database_override:
        args.database = args.database_override
    if args.table:
        validate_identifier(args.table, label="table name")
    return args


def stats_schema() -> None:
    args = parse_args()
    printing.table(schema_report(args.database, table=args.table, kind=args.kind, use_dbstat=not args.no_dbstat))
