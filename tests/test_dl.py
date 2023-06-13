import unittest
from argparse import Namespace
from unittest import mock

from xklb.db import connect
from xklb.dl_extract import dl_download
from xklb.tube_backend import download
from xklb.tube_extract import tube_add

PLAYLIST_URL = "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm"
PLAYLIST_VIDEO_URL = "https://www.youtube.com/watch?v=QoXubRvB6tQ"
STORAGE_PREFIX = "tests/data/"


class TestTube(unittest.TestCase):
    dl_db = ["tests/data/dl.db"]

    tube_db = ["tests/data/tube_dl.db"]
    tube_add([*dl_db, PLAYLIST_URL])
    tube_add([*tube_db, PLAYLIST_URL])

    def test_yt(self):
        tube_add([*self.dl_db, PLAYLIST_URL])

        args = Namespace(
            database=self.dl_db[0],
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

    @mock.patch("xklb.tube_backend.download")
    @mock.patch("xklb.tube_backend.get_playlist_metadata")
    def test_tube_dl_conversion(self, get_playlist_metadata, mocked_yt):
        tube_add([*self.tube_db, "--force", PLAYLIST_URL])
        out = get_playlist_metadata.call_args[0][1]
        assert out == PLAYLIST_URL

        dl_download([*self.tube_db, "--prefix", STORAGE_PREFIX, "--video"])
        out = mocked_yt.call_args[0]
        assert out[1]["path"] == PLAYLIST_VIDEO_URL
