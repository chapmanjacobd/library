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

    lb(["database", "filesystem", "list", db1, "-s", "conftest.py"])
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


def test_needs_process_pool_only_routes_text(monkeypatch):
    """Only text extraction is not thread-safe (textract starts its own pool). Images use
    thread-safe subprocesses (process_image/ImageMagick) and exiftool runs in the main
    process, so both audio/video and image files stay in the ThreadPoolExecutor."""
    monkeypatch.setattr(fs_add.arggroups, "text_profile_available", lambda: True)
    args = SimpleNamespace(
        profiles=[DBType.video, DBType.audio], scan_all_files=False, ocr=False, speech_recognition=False
    )
    assert fs_add.needs_process_pool(args, "/x/clip.mp4") is False
    assert fs_add.needs_process_pool(args, "/x/song.mp3") is False

    image_args = SimpleNamespace(profiles=[DBType.image], scan_all_files=False, ocr=False, speech_recognition=False)
    assert fs_add.needs_process_pool(image_args, "/x/photo.jpg") is False
    assert fs_add.needs_process_pool(image_args, "/x/clip.mp4") is False

    text_args = SimpleNamespace(profiles=[DBType.text], scan_all_files=False, ocr=False, speech_recognition=False)
    assert fs_add.needs_process_pool(text_args, "/x/book.pdf") is True
    assert fs_add.needs_process_pool(text_args, "/x/clip.mp4") is False


def test_needs_process_pool_skips_text_without_textract(monkeypatch):
    """When textract is missing the text extraction is skipped, so the process pool is
    not needed and text files can run in the thread pool."""
    monkeypatch.setattr(fs_add.arggroups, "text_profile_available", lambda: False)
    text_args = SimpleNamespace(profiles=[DBType.text], scan_all_files=True, ocr=False, speech_recognition=False)

    assert fs_add.needs_process_pool(text_args, "/x/book.pdf") is False


def test_extract_chunk_skips_image_metadata_without_exiftool(monkeypatch):
    """A missing exiftool must skip image enrichment, not crash the scan."""
    db = _mk_db()
    args = SimpleNamespace(db=db, playlists_id=1, scan_subtitles=False, scan_all_files=False)
    media = [{"path": "/x/photo.jpg", "size": 100}]

    monkeypatch.setattr(fs_add.arggroups, "image_profile_available", lambda: False)
    monkeypatch.setattr(fs_add.objects, "is_profile", lambda _args, target: target == DBType.image)

    def boom(_media):
        raise AssertionError("exiftool must not be called when it is unavailable")

    monkeypatch.setattr(fs_add, "extract_image_metadata_chunk", boom)

    fs_add.extract_chunk(args, media)

    assert len(list(db["media"].rows)) == 1


def test_extract_metadata_process_dispatches_by_extension(monkeypatch, tmp_path):
    """With `auto` (or any multi-profile set) the audio branch is enabled for every file,
    so `--process` must dispatch on the file extension: an image goes to process_image,
    never process_ffmpeg."""
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)

    args = SimpleNamespace(
        profiles=[DBType.video, DBType.audio, DBType.image, DBType.text],
        process=True,
        split_longer_than=None,
        ocr=False,
        speech_recognition=False,
        hash=False,
        copy=False,
        move=False,
    )
    monkeypatch.setattr(fs_add_metadata.file_utils, "detect_mimetype", lambda _: "image/jpeg")
    monkeypatch.setattr(fs_add_metadata.av, "munge_av_tags", lambda _args, m: m)

    calls = []
    monkeypatch.setattr(
        fs_add_metadata.process_ffmpeg, "process_path", lambda *_a, **_k: calls.append("ffmpeg") or str(photo)
    )
    monkeypatch.setattr(
        fs_add_metadata.process_image, "process_path", lambda *_a, **_k: calls.append("image") or str(photo)
    )

    fs_add_metadata.extract_metadata(args, str(photo))

    assert calls == ["image"]


def test_extract_metadata_skips_text_without_textract(monkeypatch, tmp_path):
    """A missing textract must skip text extraction, not crash the scan."""
    book = tmp_path / "book.txt"
    book.write_text("hello")

    def boom(_path):
        raise AssertionError("textract path must be skipped when it is unavailable")

    monkeypatch.setattr(fs_add_metadata.arggroups, "text_profile_available", lambda: False)
    monkeypatch.setattr(fs_add_metadata, "munge_book_tags_fast", boom)

    mp_args = SimpleNamespace(profiles=[DBType.text], scan_all_files=False, ocr=False, speech_recognition=False)
    m = fs_add_metadata.extract_metadata(mp_args, str(book))

    assert m["path"] == str(book)
    assert "tags" not in m
