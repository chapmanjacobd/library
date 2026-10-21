import re
import sqlite3
from pathlib import Path
from urllib.parse import quote


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(identifier: str, *, label: str = "identifier") -> str:
    if not IDENTIFIER_RE.fullmatch(identifier):
        message = f"invalid {label}: {identifier!r}"
        raise ValueError(message)
    return identifier


def quote_identifier(identifier: str, *, label: str = "identifier") -> str:
    return f'"{validate_identifier(identifier, label=label)}"'


def readonly_uri(database: str | Path) -> str:
    database = str(database)
    if database == ":memory:":
        return database
    path = Path(database).expanduser().resolve()
    return f"file:{quote(str(path), safe='/')}?mode=ro"


def connect_readonly(database: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(readonly_uri(database), uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def table_names(connection: sqlite3.Connection, selected: str | None = None) -> list[str]:
    if selected is not None:
        validate_identifier(selected, label="table name")
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (selected,),
        ).fetchone()
        if row is None:
            message = f"table not found: {selected!r}"
            raise ValueError(message)
        return [selected]

    return [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def table_info(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(connection.execute(f"PRAGMA table_info({quote_identifier(table, label='table name')})"))
