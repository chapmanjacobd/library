import pytest

from library.__main__ import library as lb
from tests.utils import connect_db_args


@pytest.mark.skip("CloudFlare bot blocking...")
def test_web_add(temp_db):
    db1 = temp_db()
    lb(["web-add", "--fs", db1, "https://unli.xyz/proliferation/"])

    args = connect_db_args(db1)
    media = list(args.db.query("SELECT * FROM media"))

    assert len(media) >= 4
