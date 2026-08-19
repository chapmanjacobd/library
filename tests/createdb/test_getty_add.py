import sqlite3
from unittest import mock

from library.createdb import getty_add
from library.mediadb import db_media, db_playlists
from library.utils import consts, db_utils
from library.utils.objects import NoneSpace


def test_getty_uses_standard_media_schema():
    args = NoneSpace(
        database=None,
        verbose=0,
        action="getty-add",
        profile=consts.DBType.image,
        extractor_config={},
    )
    args.db = db_utils.connect(args, conn=sqlite3.connect(":memory:"))
    db_playlists.create(args)
    db_media.create(args)
    args.db["activity_stream"].insert(
        {"path": "https://data.getty.edu/museum/collection/object/1", "type": "HumanMadeObject"},
        alter=True,
    )

    with mock.patch.object(getty_add, "getty_fetch", return_value=None):
        getty_add.update_objects(args)

    media = args.db.pop_dict("SELECT * FROM media")
    assert media["path"] == "https://data.getty.edu/museum/collection/object/1"
    assert media["playlists_id"] == 1
    assert media["object_path"] == media["path"]
    assert args.db.pop("SELECT path FROM playlists") == getty_add.GETTY_COLLECTION_URL
