from tests.utils import connect_db_args
from xklb.__main__ import library as lb

simple = '{"A": 1, "B": 3, "C": 5}\n{"A": 2, "B": 4, "C": 6}'


def test_tables_add_stdin(mock_stdin, temp_db, assert_unchanged):
    db1 = temp_db()
    with mock_stdin(simple):
        lb(["tables-add", db1, "--from-json"])

    args = connect_db_args(db1)
    result = list(args.db.query("select * from media"))
    assert_unchanged(result)


def test_tables_add_file(temp_db, assert_unchanged):
    db1 = temp_db()
    lb(["tables-add", db1, "tests/data/test.xml"])

    args = connect_db_args(db1)
    result = list(args.db.query("select * from media"))
    assert_unchanged(result)
