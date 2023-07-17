from argparse import Namespace

from tests.utils import dvd
from xklb.db import connect
from xklb.tube_backend import download
from xklb.tube_extract import tube_add

PLAYLIST_URL = "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm"
PLAYLIST_VIDEO_URL = "https://www.youtube.com/watch?v=QoXubRvB6tQ"
STORAGE_PREFIX = "tests/data/"

dl_db = ["tests/data/dl.db"]
tube_db = ["tests/data/tube_dl.db"]
# tube_add([*dl_db, PLAYLIST_URL])


@dvd.use_cassette
def test_yt():
    tube_add([*dl_db, PLAYLIST_URL])

    args = Namespace(
        database=dl_db[0],
        profile="video",
        extractor_config={},
        prefix=STORAGE_PREFIX,
        ext=None,
        ignore_errors=False,
        small=False,
        verbose=0,
        download_archive="test",
        subtitle_languages=None,
        subs=False,
        auto_subs=False,
    )  # remember to add args to dl_extract if they need to be added here
    args.db = connect(args)
    download(args, {"path": PLAYLIST_VIDEO_URL, "extractor_config": "{}"})
