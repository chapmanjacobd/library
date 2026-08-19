import sqlite3
import tempfile
from types import SimpleNamespace
from unittest import mock

from library.__main__ import library as lb
from library.createdb import fs_add, fs_add_metadata
from library.utils import db_utils
from library.utils.consts import DBType


@mock.patch("library.playback.media_printer.media_printer")
def test_fsupdate_parentpath_first(mocked, temp_db):
    db1 = temp_db()
    lb(["fsadd", db1, "tests/"])
    lb(["fsadd", db1, "tests/data/"])

    lb(["playlists", db1])
    out = mocked.call_args[0][1]
    assert len(out) == 1
    assert out[0]["path"].endswith("tests")


@mock.patch("library.playback.media_printer.media_printer")
def test_fsupdate_subpath_first(mocked, temp_db):
    db1 = temp_db()
    lb(["fsadd", db1, "tests/data/"])
    lb(["fsadd", db1, "tests/"])

    lb(["playlists", db1])
    out = mocked.call_args[0][1]
    assert len(out) == 1
    assert out[0]["path"].endswith("tests")


@mock.patch("library.playback.media_printer.media_printer")
def test_fsupdate_multi(mocked, temp_db):
    db1 = temp_db()
    lb(["fsadd", "--fs", db1, "tests/data/", "tests/conftest.py"])
    lb(["fsadd", "--fs", db1, "library/assets/"])

    lb(["playlists", db1])
    out = mocked.call_args[0][1]
    assert len(out) == 2

    lb(["fs", db1, "-s", "conftest.py"])
    out = mocked.call_args[0][1]
    assert len(out) == 1


def test_extract_metadata_expands_split_outputs(monkeypatch, tmp_path):
    source = tmp_path / "source.mp3"
    outputs = [tmp_path / "source.000.mka", tmp_path / "source.001.mka"]
    source.write_bytes(b"x")
    for output in outputs:
        output.write_bytes(b"x")

    args = SimpleNamespace(
        profile=DBType.audio,
        process=True,
        split_longer_than=None,
        ocr=False,
        speech_recognition=False,
        hash=False,
    )
    monkeypatch.setattr(fs_add_metadata.file_utils, "detect_mimetype", lambda _: "audio/mpeg")
    monkeypatch.setattr(fs_add_metadata.objects, "is_profile", lambda _args, profile: profile == DBType.audio)
    monkeypatch.setattr(fs_add_metadata.av, "munge_av_tags", lambda _args, metadata: metadata)
    monkeypatch.setattr(
        fs_add_metadata.process_ffmpeg,
        "process_path",
        lambda *_args, **_kwargs: [str(output) for output in outputs],
    )

    metadata = fs_add_metadata.extract_metadata(args, str(source))

    assert metadata is not None
    assert [item["path"] for item in metadata] == [str(output) for output in outputs]


def _mk_db():
    db_path = tempfile.mktemp(".db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE media (id INTEGER PRIMARY KEY, playlists_id int, path text, size int, time_created int)")
    conn.execute("CREATE TABLE captions (media_id int, time int, text str)")
    conn.commit()
    conn.close()
    return db_utils.connect(SimpleNamespace(database=db_path, verbose=0))


def test_extract_chunk_scan_all_files_no_duplicates():
    # 4.1: `... or is_scan_all_files` puts the entire media list into BOTH
    # image_media and other_media, processing every file twice.
    db = _mk_db()

    args = SimpleNamespace(db=db, playlists_id=1, scan_subtitles=False, scan_all_files=True)
    media = [
        {"path": "/x/photo.jpg", "size": 100},
        {"path": "/y/song.mp3", "size": 200},
    ]

    with (
        mock.patch("library.createdb.fs_add.objects.is_profile", return_value=True),
        mock.patch("library.createdb.fs_add.extract_image_metadata_chunk", side_effect=lambda m: m),
    ):
        fs_add.extract_chunk(args, media)

    rows = list(db["media"].rows)
    assert len(rows) == 2


def test_extract_chunk_writes_tag_captions():
    # 4.1: extract_chunk writes the key captions_t0 but checks/inserts caption_t0,
    # so file-tag captions are never written to the captions table.
    db = _mk_db()

    args = SimpleNamespace(db=db, playlists_id=1, scan_subtitles=False, scan_all_files=False)
    media = [{"path": "/x/file.mp4", "size": 100, "tags": "some tags\nmore"}]

    with mock.patch("library.createdb.fs_add.objects.is_profile", return_value=False):
        fs_add.extract_chunk(args, media)

    captions = list(db["captions"].rows)
    assert len(captions) == 1
    assert captions[0]["text"] == "some tags\nmore"
