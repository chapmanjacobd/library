import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from library.utils import path_utils, processes

PROCESSED_EXTENSIONS = frozenset({"avif", "srt", "vtt"})
VIDEO_CODEC = "av1"
AUDIO_CODEC = "opus"


def _has_codec(codecs, expected: str) -> bool:
    if not codecs:
        return False
    return expected in {part.strip().lower() for part in str(codecs).replace(",", " ").split()}


def _metadata_result(media: dict) -> bool | None:
    video_count = media.get("video_count")
    audio_count = media.get("audio_count")
    video_codecs = media.get("video_codecs")
    audio_codecs = media.get("audio_codecs")

    if video_count is not None and video_count > 0:
        return _has_codec(video_codecs, VIDEO_CODEC)
    if video_count == 0 and audio_count is not None and audio_count > 0:
        return _has_codec(audio_codecs, AUDIO_CODEC)
    if video_codecs or audio_codecs:
        return _has_codec(video_codecs, VIDEO_CODEC) or _has_codec(audio_codecs, AUDIO_CODEC)
    return None


def is_processed(media: dict | str | os.PathLike) -> bool:  # noqa: PLR0911
    """Return whether a media path has one of the library's processed codecs."""
    if isinstance(media, dict):
        path = str(media.get("path", ""))
        if path_utils.ext(path) in PROCESSED_EXTENSIONS:
            return True
        metadata_result = _metadata_result(media)
        if metadata_result is not None:
            return metadata_result
    else:
        path = os.fspath(media)

    if path_utils.ext(path) in PROCESSED_EXTENSIONS:
        return True

    parsed = urlparse(path)
    if parsed.scheme in {"http", "https"} or not Path(path).is_file():
        return False

    try:
        probe = processes.FFProbe(path)
    except (TimeoutError, subprocess.TimeoutExpired, processes.UnplayableFileError):
        return False

    if probe.has_video:
        return any(stream.get("codec_name") == VIDEO_CODEC for stream in probe.video_streams)
    if probe.has_audio:
        return any(stream.get("codec_name") == AUDIO_CODEC for stream in probe.audio_streams)
    return False
