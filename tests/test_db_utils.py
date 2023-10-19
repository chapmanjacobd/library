import pytest

from xklb.utils import db_utils


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
    db_utils.construct_search_bindings(mock_args, columns)

    assert "col1 LIKE :include0 OR col2 LIKE :include0" in mock_args.filter_sql[0]
    assert mock_args.filter_bindings["include0"] == "%test%"


def test_exact_match(mock_args):
    mock_args.include = ["test"]
    mock_args.exact = True
    columns = ["col1"]
    db_utils.construct_search_bindings(mock_args, columns)

    assert "col1 LIKE :include0" in mock_args.filter_sql[0]
    assert mock_args.filter_bindings["include0"] == "test"


def test_excludes(mock_args):
    mock_args.exclude = ["test"]
    columns = ["col1", "col2"]
    db_utils.construct_search_bindings(mock_args, columns)

    assert (
        "AND (COALESCE(col1,'') NOT LIKE :exclude0 AND COALESCE(col2,'') NOT LIKE :exclude0)" in mock_args.filter_sql[0]
    )
    assert mock_args.filter_bindings["exclude0"] == "%test%"


def test_exact_exclude(mock_args):
    mock_args.exclude = ["test"]
    mock_args.exact = True
    columns = ["col1"]
    db_utils.construct_search_bindings(mock_args, columns)

    assert "AND (COALESCE(col1,'') NOT LIKE :exclude0)" in mock_args.filter_sql[0]
    assert mock_args.filter_bindings["exclude0"] == "test"
