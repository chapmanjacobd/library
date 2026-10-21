"""Poll a SQLite database for newly inserted rows without writing to it."""

import argparse
import sqlite3
import time
from typing import Any

from library.database.manage._readonly import connect_readonly, quote_identifier, table_info
from library.utils import argparse_utils, printing


def _table_cursor(connection, table: str) -> dict[str, Any] | None:
    columns = table_info(connection, table)
    primary_key = [row["name"] for row in columns if row["pk"]]
    table_list = connection.execute("PRAGMA table_list").fetchall()
    without_rowid = any(row["name"] == table and row["wr"] for row in table_list)
    if len(primary_key) == 1 and without_rowid:
        return {"column": primary_key[0], "kind": "primary-key", "value": None}
    if without_rowid:
        return None
    try:
        connection.execute(f"SELECT rowid FROM {quote_identifier(table)} LIMIT 0")  # noqa: S608 - table is metadata
    except sqlite3.OperationalError:
        return None
    return {"column": "rowid", "kind": "rowid", "value": None}


def get_initial_cursors(connection, selected: str | None = None) -> dict[str, dict[str, Any]]:
    if selected is not None:
        table_names = [selected]
        if not any(
            row[0] == selected
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (selected,)
            )
        ):
            message = f"table not found: {selected!r}"
            raise ValueError(message)
    else:
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
    cursors = {}
    for table in table_names:
        cursor = _table_cursor(connection, table)
        if cursor is None:
            continue
        column = cursor["column"]
        expression = "rowid" if column == "rowid" else quote_identifier(column)
        value = connection.execute(
            f"SELECT MAX({expression}) FROM {quote_identifier(table)}"  # noqa: S608 - identifiers come from SQLite metadata
        ).fetchone()[0]
        cursor["value"] = value
        cursors[table] = cursor
    return cursors


def tail_once(
    connection,
    cursors: dict[str, dict[str, Any]],
    *,
    limit: int = 100,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    updated = {table: dict(cursor) for table, cursor in cursors.items()}
    events = []
    for table, cursor in cursors.items():
        column = cursor["column"]
        expression = "rowid" if column == "rowid" else quote_identifier(column)
        previous = cursor["value"]
        comparison = "IS NOT NULL" if previous is None else "> ?"
        params = () if previous is None else (previous,)
        query = (
            f"SELECT {expression} AS __library_tail_key, * FROM {quote_identifier(table)} "  # noqa: S608 - identifiers come from SQLite metadata
            f"WHERE {expression} {comparison} ORDER BY {expression} LIMIT ?"
        )
        result = connection.execute(query, (*params, limit))
        rows = result.fetchall()
        if not rows:
            continue
        columns = [column["name"] for column in table_info(connection, table)]
        for row in rows:
            key = row[0]
            data = dict(zip(columns, row[1:], strict=False))
            if column == "rowid" and "rowid" not in data:
                data = {"rowid": key, **data}
            events.append({"table": table, "key": key, "row": data})
        updated[table]["value"] = rows[-1][0]
    return updated, events


def poll_once(
    connection,
    cursors: dict[str, dict[str, Any]],
    *,
    limit: int = 100,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    return tail_once(connection, cursors, limit=limit)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("--db", dest="database_override", metavar="DATABASE")
    parser.add_argument("--table")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--iterations", type=int)
    args = parser.parse_args(argv)
    if args.database_override:
        args.database = args.database_override
    if args.interval < 0:
        parser.error("--interval must not be negative")
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.iterations is not None and args.iterations < 1:
        parser.error("--iterations must be positive")
    return args


def tail() -> None:
    args = parse_args()
    connection = connect_readonly(args.database)
    try:
        cursors = get_initial_cursors(connection, args.table)
        iterations = 0
        while True:
            cursors, events = tail_once(connection, cursors, limit=args.limit)
            for event in events:
                print(f"{event['table']}:")
                printing.table([event["row"]])
            iterations += 1
            if args.once or args.iterations == iterations:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return
    finally:
        connection.close()


sqlite_tail = tail
