from pytest import skip

from library.mediafiles import media_check
from library.utils import nums


def test_decode_full_scan():
    assert media_check.decode_full_scan("tests/data/test.mp4") == 0
    assert media_check.decode_full_scan("tests/data/corrupt.mp4") == 0.03333333333333336


@skip("slow")
def test_decode_quick_scan():
    assert media_check.decode_quick_scan("tests/data/test.mp4", nums.calculate_segments(12, 1)) == 0
    assert media_check.decode_quick_scan("tests/data/test.mp4", nums.calculate_segments(12, 11)) == 0

    assert media_check.decode_quick_scan("tests/data/corrupt.mp4", nums.calculate_segments(12, 0.1), 1) == 1.0
    assert media_check.decode_quick_scan("tests/data/corrupt.mp4", nums.calculate_segments(12, 0.5), 1) == 1.0
    assert media_check.decode_quick_scan("tests/data/corrupt.mp4", nums.calculate_segments(12, 1), 1) == 1.0
    assert media_check.decode_quick_scan("tests/data/corrupt.mp4", nums.calculate_segments(12, 2), 1) == 1.0
    assert media_check.decode_quick_scan("tests/data/corrupt.mp4", nums.calculate_segments(12, 3), 1) == 1.0
