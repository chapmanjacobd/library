from types import SimpleNamespace

from library.file import processed
from library.utils import filter_engine


def test_processed_extensions_are_already_processed():
    assert processed.is_processed("cover.avif")
    assert processed.is_processed("captions.srt")
    assert processed.is_processed("captions.vtt")


def test_processed_uses_database_codec_metadata_for_remote_paths():
    assert processed.is_processed({"path": "https://example.test/video.mp4", "video_count": 1, "video_codecs": "av1"})
    assert not processed.is_processed(
        {"path": "https://example.test/video.mp4", "video_count": 1, "video_codecs": "h264"}
    )
    assert processed.is_processed(
        {"path": "https://example.test/audio.m4a", "video_count": 0, "audio_count": 1, "audio_codecs": "opus"}
    )


def test_processed_probes_local_media(monkeypatch, tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"media")
    probe = SimpleNamespace(
        has_video=True,
        has_audio=True,
        video_streams=[{"codec_name": "av1"}],
        audio_streams=[{"codec_name": "aac"}],
    )
    monkeypatch.setattr(processed.processes, "FFProbe", lambda _path: probe)

    assert processed.is_processed(path)


def test_filter_processed_selects_requested_status():
    args = SimpleNamespace(processed=True)
    items = [
        {"path": "one.avif"},
        {"path": "two.mp4"},
        {"path": "three.srt"},
    ]

    assert [item["path"] for item in filter_engine.filter_processed(args, items)] == ["one.avif", "three.srt"]


def test_database_filter_applies_limit_after_processed_filter():
    class Database:
        def query(self, _query, _bindings):
            return [
                {"path": "unprocessed.mp4", "video_count": 1, "video_codecs": "h264"},
                {"path": "processed.mp4", "video_count": 1, "video_codecs": "av1"},
            ]

    args = SimpleNamespace(
        database="media.db",
        db=Database(),
        processed=True,
        limit=1,
        offset=0,
        type=[],
        no_type=[],
        include=[],
    )

    items = filter_engine.FilterEngine(args).get_filtered_data(db_sql_func=lambda _args: ("query", {}))

    assert [item["path"] for item in items] == ["processed.mp4"]
