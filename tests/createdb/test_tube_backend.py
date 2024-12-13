from types import SimpleNamespace
from unittest import skip

import pytest

from library.createdb import tube_backend
from library.utils.consts import DLStatus

mock_webpath = "https://test/"


def test_get_video_download_environment_error():
    ydl_log = {"error": ["No space left on device"], "warning": [], "info": []}
    with pytest.raises(SystemExit) as e:
        tube_backend.log_error(ydl_log, mock_webpath)
    assert e.value.code == 28


def test_get_video_download_ure():
    error_msg = "[download] x: has already been recorded in the archive"
    ydl_log = {"error": [], "warning": ["Unrelated warning"], "info": [error_msg]}
    assert tube_backend.log_error(ydl_log, mock_webpath) == (DLStatus.UNRECOVERABLE_ERROR, error_msg)


def test_get_video_download_re():
    error_msg = "HTTP Error 429"
    ydl_log = {"error": [], "warning": [error_msg], "info": []}
    assert tube_backend.log_error(ydl_log, mock_webpath) == (DLStatus.RECOVERABLE_ERROR, error_msg)


def test_get_video_download_unknown():
    ydl_log = {"error": ["Unknown error"], "warning": ["Unknown warning"], "info": []}
    assert tube_backend.log_error(ydl_log, mock_webpath) == (DLStatus.UNKNOWN_ERROR, "Unknown error\nUnknown warning")


def test_safe_mode():
    assert tube_backend.is_supported("https://youtu.be/HoY5RbzRcmo")
    assert tube_backend.is_supported("https://www.youtube.com/watch?v=l9-w69bPApk")
    assert tube_backend.is_supported("https://v.redd.it/c4jylachq3s81")
    assert tube_backend.is_supported("https://old.reddit.com/r/memes/comments/n1wk0w/its_going/")
    assert tube_backend.is_supported("www.com") is False


@skip("network")
def test_get_video_metadata():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    tube_backend.get_video_metadata(args, "https://www.youtube.com/watch?v=hRVgC7eE-Ow")


@skip("network")
def test_get_video_metadata_playlist():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    tube_backend.get_video_metadata(
        args,
        "https://www.youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm",
    )
    tube_backend.get_video_metadata(args, "https://www.youtube.com/@ZeducationTyler")
