from tests.playback import test_tabs_open
from tests.utils import connect_db_args
from xklb.lb import library as lb


def test_tabs_add(temp_db):
    db1 = temp_db()
    lb(["tabs-add", db1, test_tabs_open.TEST_URL])

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) == 1
    assert media[0]["frequency"] == "monthly"
