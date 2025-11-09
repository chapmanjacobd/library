from types import SimpleNamespace

import pytest
import pytest

from library.createdb import tube_backend
from library.utils.consts import DLStatus

mock_webpath = "https://test/"


def test_get_video_download_environment_error():
    ydl_log = {"error": ["No space left on device"], "warning": [], "info": []}
    with pytest.raises(SystemExit) as excinfo:
        tube_backend.log_error(ydl_log, mock_webpath)
    assert excinfo.value.code == 28


@pytest.mark.parametrize(
    "ydl_log, saved_error",
    [
        (
            {
                "error": [],
                "warning": ["Unrelated warning"],
                "info": ["[download] x: has already been recorded in the archive"],
            },
            "[download] x: has already been recorded in the archive",
        ),
        (
            {
                "error": [
                    "\x1b[0;31mERROR:\x1b[0m [youtube] x: Private video. Sign in if you've been granted access to this video. Use --cookies-from-browser or --cookies for the authentication. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for how to manually pass cookies. Also see https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies for tips on effectively exporting YouTube cookies",
                    "ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video. Use --cookies-from-browser or --cookies for the authentication. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for how to manually pass cookies. Also see https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies for tips on effectively exporting YouTube cookies",
                ],
                "warning": [],
                "info": [
                    "[youtube] Extracting URL: https://youtube.com/watch?v=x",
                    "[youtube] x: Downloading webpage",
                    "[youtube] x: Downloading tv client config",
                    "[youtube] x: Downloading player 7b9b4e02-main",
                    "[youtube] x: Downloading tv player API JSON",
                    "[youtube] x: Downloading android sdkless player API JSON",
                ],
            },
            "\x1b[0;31mERROR:\x1b[0m [youtube] x: Private video. Sign in if you've been granted access to this video. Use --cookies-from-browser or --cookies for the authentication. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for how to manually pass cookies. Also see https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies for tips on effectively exporting YouTube cookies;ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video. Use --cookies-from-browser or --cookies for the authentication. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for how to manually pass cookies. Also see https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies for tips on effectively exporting YouTube cookies",
        ),
    ],
)
def test_log_error_ure(ydl_log, saved_error):
    assert tube_backend.log_error(ydl_log, mock_webpath) == (DLStatus.UNRECOVERABLE_ERROR, saved_error)


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


@pytest.mark.skip("network")
def test_get_video_metadata():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    tube_backend.get_video_metadata(args, "https://www.youtube.com/watch?v=hRVgC7eE-Ow")


@pytest.mark.skip("network")
def test_get_video_metadata_playlist():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    tube_backend.get_video_metadata(
        args,
        "https://www.youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm",
    )
    tube_backend.get_video_metadata(args, "https://www.youtube.com/@ZeducationTyler")
