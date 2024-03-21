from argparse import Namespace

from xklb.lb import library as lb
from xklb.tube_extract import tube_add
from xklb.utils.db_utils import connect

URL = "https://www.youtube.com/watch?v=BaW_jenozKc"
# PLAYLIST_URL = "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm"
# PLAYLIST_VIDEO_URL = "https://www.youtube.com/watch?v=QoXubRvB6tQ"
STORAGE_PREFIX = "tests/data/"

dl_db = ["tests/data/dl.db"]
# tube_add([*dl_db, PLAYLIST_URL])


def test_yt():
    tube_add([*dl_db, URL])
    lb(
        [
            "dl",
            *dl_db,
            "--video",
            f"--prefix={STORAGE_PREFIX}",
            "--no-write-thumbnail",  # TODO: test that yt-dlp option is forwarded
            "--force",
            "--subs",
            "-s",
            URL,
        ]
    )

    args = Namespace(database=dl_db[0], verbose=0)
    args.db = connect(args)

    captions = list(args.db.query("select * from captions"))
    assert {"media_id": 2, "time": 3, "text": "For more information contact phihag@phihag.de"} in captions
