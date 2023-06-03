from types import SimpleNamespace
from unittest import skip

from xklb import tube_backend


@skip("network")
def test_get_video_metadata():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    data = tube_backend.get_video_metadata(args, "https://www.youtube.com/watch?v=hRVgC7eE-Ow")
    raise


@skip("network")
def test_get_video_metadata_playlist():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    data = tube_backend.get_video_metadata(
        args, "https://www.youtube.com/playlist?list=PLQoygnhlz2LhnqLUuQQ0Z67fwouadzGIf"
    )
    raise


@skip("network")
def test_get_video_metadata_channel():
    args = SimpleNamespace(verbose=0, ignore_errors=False)
    data = tube_backend.get_video_metadata(args, "https://www.youtube.com/@ZeducationTyler")
    raise
