import unittest
from unittest.mock import patch

from xklb.utils import consts, db_utils, sql_utils


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
        self.assertEqual(result, "table1")

    def test_partial_match(self):
        existing_tables = {
            "table1": {"id": "INT", "name": "VARCHAR", "age": "INT"},
            "table2": {"id": "INT", "email": "VARCHAR", "phone": "VARCHAR"},
        }
        keys = ["id", "name", "address", "age"]
        result = db_utils.most_similar_schema(keys, existing_tables)
        self.assertEqual(result, "table1")

    def test_no_match(self):
        existing_tables = {
            "table1": {"id": "INT", "name": "VARCHAR", "age": "INT"},
            "table2": {"id": "INT", "email": "VARCHAR", "phone": "VARCHAR"},
        }
        keys = ["salary", "position", "department"]
        result = db_utils.most_similar_schema(keys, existing_tables)
        self.assertIsNone(result)

    def test_empty_input(self):
        existing_tables = {
            "table1": {"id": "INT", "name": "VARCHAR", "age": "INT"},
            "table2": {"id": "INT", "email": "VARCHAR", "phone": "VARCHAR"},
        }
        keys = []
        result = db_utils.most_similar_schema(keys, existing_tables)
        self.assertIsNone(result)
