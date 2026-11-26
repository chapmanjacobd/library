import pytest

from library.__main__ import library as lb
from tests.utils import connect_db_args


def test_lb_row_add_success(temp_db):
    db1 = temp_db()
    lb(["row-add", db1, "--test_b", "1", "--test-a", "2"])

    args = connect_db_args(db1)
    result = list(args.db.query("select * from media"))

    assert result == [{"test_b": 1, "test_a": 2}]


def test_lb_row_add_db_flag(temp_db):
    db1 = temp_db()
    lb(["row-add", "--db", db1, "--test_b", "1"])

    args = connect_db_args(db1)
    result = list(args.db.query("select * from media"))

    assert result == [{"test_b": 1}]


def test_lb_row_add_missing_arguments(temp_db):
    db1 = temp_db()
    with pytest.raises(SystemExit):
        lb(["row-add", db1])
