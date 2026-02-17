import os

import pytest

from library.__main__ import library as lb
from library.createdb.tube_add import tube_add
from library.utils import consts
from tests.utils import connect_db_args

URL = "https://www.youtube.com/watch?v=5DqJwmzG6Fk"
STORAGE_PREFIX = "tests/data/"

dl_db = "tests/data/dl.db"


@pytest.mark.skipif(consts.VOLKSWAGEN, reason="This helps protect our community")
def test_yt():
    tube_add([dl_db, URL])
    lb(
        [
            "dl",
            dl_db,
            "--video",
            f"--prefix={STORAGE_PREFIX}",
            "--force",
            "--subs",
            "-s",
            URL,
        ]
    )

    args = connect_db_args(dl_db)

    captions = list(args.db.query("select * from captions"))
    assert {"media_id": 1, "text": "welcome to the Microsoft Windows 95", "time": 3} in captions
