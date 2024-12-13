from tests.utils import connect_db_args
from library.__main__ import library as lb


def test_tildes_add(temp_db):
    db1 = temp_db()
    lb(["tildes", db1, "xk3"])

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) >= 5
