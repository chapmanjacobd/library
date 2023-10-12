from unittest import skip

from xklb import av


def test_decode_full_scan():
    assert av.decode_full_scan("tests/data/test.mp4") == 0
    assert av.decode_full_scan("tests/data/corrupt.mp4") == 0.03389830508474579


@skip("slow")
def test_decode_quick_scan():
    assert av.decode_quick_scan("tests/data/test.mp4", *av.cover_scan(12, 1)) == 0
    assert av.decode_quick_scan("tests/data/test.mp4", *av.cover_scan(12, 99)) == 0

    assert av.decode_quick_scan("tests/data/corrupt.mp4", *av.cover_scan(12, 10)) == 0.6666666666666666
    assert av.decode_quick_scan("tests/data/corrupt.mp4", *av.cover_scan(12, 20)) == 0.80
    assert av.decode_quick_scan("tests/data/corrupt.mp4", *av.cover_scan(12, 40)) == 0.8888888888888888
    assert av.decode_quick_scan("tests/data/corrupt.mp4", *av.cover_scan(12, 50)) == 0.9166666666666666
