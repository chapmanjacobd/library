import os

import pytest

from library.__main__ import library as lb
from library.createdb.tube_add import tube_add
from tests.utils import connect_db_args

URL = "https://www.youtube.com/watch?v=W5ZLFBZkE34"
STORAGE_PREFIX = "tests/data"

dl_db = "tests/data/live.db"


@pytest.mark.skip("network")
def test_live_skip():
    tube_add([dl_db, URL])
    lb(
        [
            "dl",
            dl_db,
            "--video",
            "-o",
            f"{STORAGE_PREFIX}/%(id)s.%(ext)s",
            URL,
        ]
    )

    args = connect_db_args(dl_db)

    video_path = os.path.join(STORAGE_PREFIX, "W5ZLFBZkE34.mkv")
    assert not os.path.exists(video_path), "Video file exists"


@pytest.mark.skip("network")
def test_live():
    tube_add([dl_db, URL])
    lb(
        [
            "dl",
            dl_db,
            "--video",
            "-o",
            f"{STORAGE_PREFIX}/%(id)s.%(ext)s",
            "--live",
            URL,
        ]
    )

    args = connect_db_args(dl_db)

    video_path = os.path.join(STORAGE_PREFIX, "W5ZLFBZkE34.mkv")
    assert os.path.exists(video_path), "Video file does not exist"
