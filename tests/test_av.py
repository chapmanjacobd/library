from unittest import skip

import ffmpeg, pytest

from xklb import av, utils


@skip("doesn't seem to work on ffmpeg v5")
def test_decode_full_scan():
    av.decode_full_scan("tests/data/test.mp4")
    with pytest.raises(ffmpeg.Error):
        av.decode_full_scan("tests/data/corrupt.mp4")


@skip("slow; doesn't seem to work on ffmpeg v5")
def test_decode_quick_scan():
    assert av.decode_quick_scan("tests/data/test.mp4", *utils.cover_scan(12, 1)) == 0
    assert av.decode_quick_scan("tests/data/test.mp4", *utils.cover_scan(12, 99)) == 0

    assert av.decode_quick_scan("tests/data/corrupt.mp4", *utils.cover_scan(12, 10)) == 0.6666666666666666
    assert av.decode_quick_scan("tests/data/corrupt.mp4", *utils.cover_scan(12, 20)) == 0.80
    assert av.decode_quick_scan("tests/data/corrupt.mp4", *utils.cover_scan(12, 40)) == 0.8888888888888889
    assert av.decode_quick_scan("tests/data/corrupt.mp4", *utils.cover_scan(12, 50)) == 0.9166666666666666
