import unittest
from unittest.mock import patch

import pytest

from xklb.utils import consts, db_utils, sql_utils


class MockArgs:
    def __init__(self):
        self.include = []
        self.exclude = []
        self.exact = False
        self.filter_sql = []
        self.filter_bindings = {}


@pytest.fixture
def mock_args():
    return MockArgs()


def test_includes(mock_args):
    mock_args.include = ["test"]
    columns = ["col1", "col2"]
    with patch.object(consts, "random_string", return_value=""):
        sql_utils.construct_search_bindings(mock_args, columns)

    assert "col1 LIKE :include0 OR col2 LIKE :include0" in mock_args.filter_sql[0]
    assert mock_args.filter_bindings["include0"] == "%test%"


def test_exact_match(mock_args):
    mock_args.include = ["test"]
    mock_args.exact = True
    columns = ["col1"]
    with patch.object(consts, "random_string", return_value=""):
        sql_utils.construct_search_bindings(mock_args, columns)

    assert "col1 LIKE :include0" in mock_args.filter_sql[0]
    assert mock_args.filter_bindings["include0"] == "test"


def test_excludes(mock_args):
    mock_args.exclude = ["test"]
    columns = ["col1", "col2"]
    with patch.object(consts, "random_string", return_value=""):
        sql_utils.construct_search_bindings(mock_args, columns)

    assert (
        "AND (COALESCE(col1,'') NOT LIKE :exclude0 AND COALESCE(col2,'') NOT LIKE :exclude0)" in mock_args.filter_sql[0]
    )
    assert mock_args.filter_bindings["exclude0"] == "%test%"


def test_exact_exclude(mock_args):
    mock_args.exclude = ["test"]
    mock_args.exact = True
    columns = ["col1"]
    with patch.object(consts, "random_string", return_value=""):
        sql_utils.construct_search_bindings(mock_args, columns)

    assert "AND (COALESCE(col1,'') NOT LIKE :exclude0)" in mock_args.filter_sql[0]
    assert mock_args.filter_bindings["exclude0"] == "test"


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
