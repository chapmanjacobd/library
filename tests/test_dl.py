import shutil, unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from xklb import paths
from xklb.db import connect
from xklb.dl_extract import dl_add, dl_block, dl_download, dl_update, yt
from xklb.lb import lb
from xklb.tube_extract import tube_add

PLAYLIST_URL = "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm"
PLAYLIST_VIDEO_URL = "https://www.youtube.com/watch?v=QoXubRvB6tQ"
STORAGE_PREFIX = "tests/data/"

dl_db = "--db", "tests/data/dl.db"

tube_db = "--db", "tests/data/tube_dl.db"
tube_add([*tube_db, PLAYLIST_URL])


class TestTube(unittest.TestCase):
    def init_db(self):
        dl_add([*dl_db, "Self", PLAYLIST_URL])

    def test_yt(self):
        dl_db = "--db", "tests/data/dl.db"
        dl_add([*dl_db, "Self", PLAYLIST_URL])

        args = Namespace(database=dl_db[1], dl_config={}, prefix=STORAGE_PREFIX, ignore_errors=False, verbose=0)
        args.db = connect(args)
        yt(args, dict(path=PLAYLIST_VIDEO_URL, dl_config={}, category="Self"))
        Path(dl_db[1]).unlink()

    def test_yta(self):
        dl_db = "--db", "tests/data/dl.db"
        dl_add([*dl_db, "Self", PLAYLIST_URL])

        args = Namespace(
            database=dl_db[1], dl_config={}, prefix=STORAGE_PREFIX, ignore_errors=False, ext="opus", verbose=0
        )
        args.db = connect(args)
        yt(args, dict(path=PLAYLIST_VIDEO_URL, dl_config={}, category="Self"), audio_only=True)
        Path(dl_db[1]).unlink()

    @mock.patch("xklb.dl_extract.yt")
    @mock.patch("xklb.tube_extract.process_playlist")
    def test_tube_dl_conversion(self, process_playlist, yt):
        dl_add([*tube_db, "Self", PLAYLIST_URL])
        out = process_playlist.call_args[0][1]
        assert out == PLAYLIST_URL

        dl_download([*tube_db, STORAGE_PREFIX])
        out = yt.call_args[0]
        assert out[1]["path"] == PLAYLIST_VIDEO_URL

    @mock.patch("xklb.dl_extract.yt")
    def test_download(self, yt):
        self.init_db()

        dl_download([*dl_db, STORAGE_PREFIX])
        out = yt.call_args[0]
        assert out[1]["path"] == PLAYLIST_VIDEO_URL
        Path(dl_db[1]).unlink()

    @mock.patch("xklb.tube_extract.update_playlists")
    def test_dlupdate(self, update_playlists):
        self.init_db()

        dl_update([*dl_db])
        out = update_playlists.call_args[0]
        assert out[1][0]["path"] == PLAYLIST_URL
        Path(dl_db[1]).unlink()

    @mock.patch("xklb.tube_extract.update_playlists")
    def test_dlupdate_subset_category(self, update_playlists):
        self.init_db()

        dl_update([*dl_db, "Self"])
        out = update_playlists.call_args[0]
        assert out[1][0]["path"] == PLAYLIST_URL
        Path(dl_db[1]).unlink()

    def test_block(self):
        self.init_db()

        dl_block([*dl_db, PLAYLIST_URL])
        db = connect(Namespace(database=dl_db[1], verbose=0))
        playlists = list(db["playlists"].rows)
        assert playlists[0]["is_deleted"] == 1
        assert playlists[0]["category"] == paths.BLOCK_THE_CHANNEL
        Path(dl_db[1]).unlink()