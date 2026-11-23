import json
import sqlite3
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from library.utils import consts, db_utils, sql_utils


def _connect_args(database):
    return SimpleNamespace(database=str(database), verbose=0)


def _create_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE media (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT INTO media (value) VALUES (?)", [(f"row{i}",) for i in range(1000)])
    return path


def _page_count(path):
    with open(path, "rb") as f:
        header = f.read(100)
    return struct.unpack(">I", header[28:32])[0], struct.unpack(">H", header[16:18])[0]


def test_connect_valid_database(tmp_path):
    db_path = _create_db(tmp_path / "valid.db")

    db = db_utils.connect(_connect_args(db_path))

    assert db["media"].count == 1000
    db.conn.close()


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ("truncated", "truncated"),
        ("not_a_database", "corrupt"),
    ],
)
def test_connect_corrupt_database(tmp_path, caplog, mutation, expected_message):
    db_path = _create_db(tmp_path / "corrupt.db")

    if mutation == "truncated":
        page_count, page_size = _page_count(db_path)
        assert page_count > 2
        with open(db_path, "r+b") as f:
            f.truncate(page_size * 2)
    else:
        db_path.write_bytes(json.dumps({"not": "sqlite"}).encode())

    with pytest.raises(SystemExit) as excinfo:
        db_utils.connect(_connect_args(db_path))

    assert excinfo.value.code == 1
    assert str(db_path) in caplog.text
    assert expected_message in caplog.text
    assert ".recover" in caplog.text


def test_includes():
    with patch.object(consts, "random_string", return_value=""):
        search_sql, search_bindings = sql_utils.construct_search_bindings(
            include=["test"],
            exclude=[],
            columns=["col1", "col2"],
        )

    assert "col1 LIKE :S_include0 OR col2 LIKE :S_include0" in search_sql[0]
    assert search_bindings["S_include0"] == "%test%"


def test_exact_match():
    with patch.object(consts, "random_string", return_value=""):
        search_sql, search_bindings = sql_utils.construct_search_bindings(
            include=["test"], exclude=[], columns=["col1"], exact=True
        )

    assert "col1 LIKE :S_include0" in search_sql[0]
    assert search_bindings["S_include0"] == "test"


def test_excludes():
    with patch.object(consts, "random_string", return_value=""):
        search_sql, search_bindings = sql_utils.construct_search_bindings(
            include=[],
            exclude=["test"],
            columns=["col1", "col2"],
        )

    assert "AND (COALESCE(col1,'') NOT LIKE :S_exclude0 AND COALESCE(col2,'') NOT LIKE :S_exclude0)" in search_sql[0]
    assert search_bindings["S_exclude0"] == "%test%"


def test_exact_exclude():
    with patch.object(consts, "random_string", return_value=""):
        search_sql, search_bindings = sql_utils.construct_search_bindings(
            include=[], exclude=["test"], columns=["col1"], exact=True
        )

    assert "AND (COALESCE(col1,'') NOT LIKE :S_exclude0)" in search_sql[0]
    assert search_bindings["S_exclude0"] == "test"


class TestMostSimilarSchema(unittest.TestCase):
    def test_exact_match(self):
        existing_tables = {
            "table1": {"id": "INT", "name": "VARCHAR", "age": "INT"},
            "table2": {"id": "INT", "email": "VARCHAR", "phone": "VARCHAR"},
        }
        keys = ["id", "name", "age"]
        result = db_utils.most_similar_schema(keys, existing_tables)
        assert result == "table1"

    def test_partial_match(self):
        existing_tables = {
            "table1": {"id": "INT", "name": "VARCHAR", "age": "INT"},
            "table2": {"id": "INT", "email": "VARCHAR", "phone": "VARCHAR"},
        }
        keys = ["id", "name", "address", "age"]
        result = db_utils.most_similar_schema(keys, existing_tables)
        assert result == "table1"

    def test_no_match(self):
        existing_tables = {
            "table1": {"id": "INT", "name": "VARCHAR", "age": "INT"},
            "table2": {"id": "INT", "email": "VARCHAR", "phone": "VARCHAR"},
        }
        keys = ["salary", "position", "department"]
        result = db_utils.most_similar_schema(keys, existing_tables)
        assert result is None

    def test_empty_input(self):
        existing_tables = {
            "table1": {"id": "INT", "name": "VARCHAR", "age": "INT"},
            "table2": {"id": "INT", "email": "VARCHAR", "phone": "VARCHAR"},
        }
        keys = []
        result = db_utils.most_similar_schema(keys, existing_tables)
        assert result is None
