import argparse
import pytest

from xklb.media.media_player import MediaPrefetcher
from xklb.utils import consts


@pytest.fixture
def media():
    return [
        {"path": "tests/data/test.mp4"},
        {"path": "tests/data/test.opus"},
        {"path": "tests/data/test.eng.vtt"},
        {"path": "tests/data/test.vtt"},
    ]


def test_prefetch(media):
    args = argparse.Namespace(
        prefetch=2,
        database=':memory:',
        play_in_order=0,
        transcode=False,
        transcode_audio=False,
        action=consts.SC.watch,
        prefix="",
        verbose=2,
    )
    prep = MediaPrefetcher(args, media)

    assert prep.remaining == 4
    assert len(prep.media) == 4
    assert len(prep.futures) == 0

    prep.fetch()
    assert prep.remaining == 4
    assert len(prep.media) == 2
    assert len(prep.futures) == 2

    m = prep.get_m()
    assert m is not None
    assert m['path'] == "tests/data/test.mp4"
    assert prep.remaining == 3
    assert len(prep.media) == 1
    assert len(prep.futures) == 2

    m = prep.get_m()
    assert prep.remaining == 2
    assert len(prep.media) == 0
    assert len(prep.futures) == 2

    m = prep.get_m()
    assert prep.remaining == 1
    assert len(prep.media) == 0
    assert len(prep.futures) == 1

    m = prep.get_m()
    assert m is not None
    assert m['path'] == "tests/data/test.vtt"
    assert prep.remaining == 0
    assert len(prep.media) == 0
    assert len(prep.futures) == 0

    assert prep.get_m() is None
    assert prep.remaining == 0
