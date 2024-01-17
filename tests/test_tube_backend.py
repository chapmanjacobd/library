from types import SimpleNamespace

from xklb import tube_backend


def test_safe_mode():
    assert tube_backend.is_supported("https://youtu.be/HoY5RbzRcmo")
    assert tube_backend.is_supported("https://www.youtube.com/watch?v=l9-w69bPApk")
    assert tube_backend.is_supported("https://v.redd.it/c4jylachq3s81")
    assert tube_backend.is_supported("https://old.reddit.com/r/memes/comments/n1wk0w/its_going/")
    assert tube_backend.is_supported("www.com") is False


def test_get_video_metadata():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    tube_backend.get_video_metadata(args, "https://www.youtube.com/watch?v=hRVgC7eE-Ow")


def test_get_video_metadata_playlist():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    tube_backend.get_video_metadata(
        args,
        "https://www.youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm",
    )


def test_get_video_metadata_channel():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    tube_backend.get_video_metadata(args, "https://www.youtube.com/@ZeducationTyler")
