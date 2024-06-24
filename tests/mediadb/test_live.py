import os

from tests.utils import connect_db_args
from xklb.createdb.tube_add import tube_add
from xklb.lb import library as lb

URL = "https://www.youtube.com/watch?v=W5ZLFBZkE34"
STORAGE_PREFIX = "tests/data/"

dl_db = "tests/data/dl.db"


def test_yt():
    tube_add([dl_db, URL])
    lb(
        [
            "dl",
            dl_db,
            "--video",
            f"--prefix={STORAGE_PREFIX}",
            "--write-thumbnail",
            "--force",
            "--subs",
            "--live",
            "-s",
            URL,
        ]
    )

    args = connect_db_args(dl_db)

    captions = list(args.db.query("select * from captions"))
    assert {"media_id": 2, "time": 2, "text": "okay hello um so welcome to um today's"} in captions

    thumbnail_path = os.path.join(STORAGE_PREFIX, "Youtube", "Sugar Labs", "Learn： How to git involved with Sugar Labs this summer_45.00_[W5ZLFBZkE34].webp")
    assert os.path.exists(thumbnail_path), "Thumbnail file does not exist"

    video_path = os.path.join(STORAGE_PREFIX, "Youtube", "Sugar Labs", "Learn： How to git involved with Sugar Labs this summer_45.00_[W5ZLFBZkE34].mp4")
    assert os.path.exists(video_path), "Video file does not exist"
