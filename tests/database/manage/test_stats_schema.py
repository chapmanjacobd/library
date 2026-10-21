import sqlite3

import pytest

from library.database.manage import stats_schema
from library.database.manage._readonly import connect_readonly


def test_schema_report_includes_columns_indexes_and_labeled_fallback(tmp_path):
    database = tmp_path / "schema.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    connection.execute("CREATE UNIQUE INDEX items_name_idx ON items(name)")
    connection.execute("INSERT INTO items(name) VALUES ('one')")
    connection.commit()
    connection.close()

    report = stats_schema.schema_report(str(database), use_dbstat=False)
    assert {row["kind"] for row in report} == {"table", "column", "index"}
    assert all(row["stats_source"].startswith("fallback") for row in report)
    assert any(row["kind"] == "index" and row["name"] == "items_name_idx" for row in report)
    assert any(row["kind"] == "column" and row["name"] == "name" for row in report)
    readonly = connect_readonly(database)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        readonly.execute("CREATE TABLE should_fail (id INTEGER)")
    readonly.close()


@pytest.mark.parametrize("kind", ["table", "column", "index"])
def test_schema_report_filters_by_kind(tmp_path, kind):
    database = tmp_path / "schema.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    connection.execute("CREATE UNIQUE INDEX items_name_idx ON items(name)")
    connection.commit()
    connection.close()

    report = stats_schema.schema_report(str(database), kind=kind, use_dbstat=False)

    assert report
    assert {row["kind"] for row in report} == {kind}


def test_parse_args_defaults_to_all_kinds():
    args = stats_schema.parse_args(["schema.db"])

    assert args.kind is None


def test_parse_args_accepts_kind():
    args = stats_schema.parse_args(["schema.db", "--kind", "index"])

    assert args.kind == "index"
