from tests.utils import connect_db_args
from xklb.__main__ import library as lb


def test_lb_hn_add(temp_db):
    db1 = temp_db()
    lb(["hn-add", db1, "--oldest", "--max-id=5"])

    args = connect_db_args(db1)
    assert args.db.pop("SELECT COUNT(*) FROM hn_story") == 3
