import unittest
from argparse import Namespace
from unittest import mock

from xklb import paths
from xklb.db import connect
from xklb.dl_extract import dl_add, dl_block, dl_download, dl_update
from xklb.lb import lb
from xklb.tube_extract import tube_add

PLAYLIST_URL = "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm"

tube_db = "--db", "tests/data/tube_dl.db"
tube_add([*tube_db, PLAYLIST_URL])

dl_db = "--db", "tests/data/dl.db"
dl_add([*dl_db, "Self", PLAYLIST_URL])


class TestTube(unittest.TestCase):
    @mock.patch("xklb.dl_extract.yt")
    @mock.patch("xklb.tube_extract.process_playlist")
    def test_tube_dl_conversion(self, process_playlist, yt):
        dl_add([*tube_db, "Self", PLAYLIST_URL])
        out = process_playlist.call_args[0][1]
        assert out == PLAYLIST_URL

        dl_download([*tube_db, "tests/data/"])
        out = yt.call_args[0]
        raise

    @mock.patch("xklb.dl_extract.yt")
    def test_download(self, yt):
        dl_download([*dl_db, "tests/data/"])
        out = yt.call_args[0]
        raise

    @mock.patch("xklb.tube_extract.update_playlists")
    def test_dlupdate(self, update_playlists):
        dl_update([*dl_db])
        out = update_playlists.call_args[0]
        raise

    @mock.patch("xklb.tube_extract.update_playlists")
    def test_dlupdate_subset_category(self, update_playlists):
        dl_update([*dl_db, "Self"])
        out = update_playlists.call_args[0]
        raise

    def test_block(self):
        dl_block([*dl_db, PLAYLIST_URL])
        db = connect(Namespace(database=dl_db[1], verbose=0))
        playlists = list(db["playlists"].rows)
        assert playlists[0]["is_deleted"] == 1
        assert playlists[0]["title"] == paths.BLOCK_THE_CHANNEL
