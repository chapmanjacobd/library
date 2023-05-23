from unittest import skip

import ffmpeg, pytest

from xklb import utils


@skip("doesn't seem to work on ffmpeg v5")
def test_decode_full_scan():
    utils.decode_full_scan("tests/data/test.mp4")
    with pytest.raises(ffmpeg.Error):
        utils.decode_full_scan("tests/data/corrupt.mp4")


@skip("slow; doesn't seem to work on ffmpeg v5")
def test_decode_quick_scan():
    assert utils.decode_quick_scan("tests/data/test.mp4", *utils.cover_scan(12, 1)) == 0
    assert utils.decode_quick_scan("tests/data/test.mp4", *utils.cover_scan(12, 99)) == 0

    assert utils.decode_quick_scan("tests/data/corrupt.mp4", *utils.cover_scan(12, 10)) == 66.66666666666666
    assert utils.decode_quick_scan("tests/data/corrupt.mp4", *utils.cover_scan(12, 20)) == 80
    assert utils.decode_quick_scan("tests/data/corrupt.mp4", *utils.cover_scan(12, 40)) == 88.88888888888889
    assert utils.decode_quick_scan("tests/data/corrupt.mp4", *utils.cover_scan(12, 50)) == 91.66666666666666
