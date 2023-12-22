from xklb.utils.nums import calculate_segments


def test_end_segment_small_file():
    segments = calculate_segments(30, 25)
    assert segments == [(0, 30)]


def test_end_segment_zero_size():
    segments = calculate_segments(0, 25)
    assert segments == []


def test_end_segment_big_gap():
    segments = calculate_segments(100, 25, 0.9)
    assert segments == [(0, 25), (75, 25)]


def test_end_segment_medium_gap():
    segments = calculate_segments(100, 25, 0.2)
    assert segments == [(0, 25), (45, 25), (75, 25)]


def test_end_segment_small_gap():
    segments = calculate_segments(100, 25, 0.01)
    assert segments == [(0, 25), (26, 25), (75, 25)]


def test_end_segment():
    segments = calculate_segments(100, 25)
    assert segments == [(0, 25), (35, 25), (75, 25)]


def test_basic():
    segments = calculate_segments(1000, 100)
    assert segments == [(0, 100), (200, 100), (400, 100), (600, 100), (900, 100)]


def test_percent_gap():
    segments = calculate_segments(1000, 100, 0.5)
    assert segments == [(0, 100), (600, 100), (900, 100)]


def test_byte_gap():
    segments = calculate_segments(1024, 256, 512)
    assert segments == [(0, 256), (768, 256)]


def test_size_alignment():
    segments = calculate_segments(555, 100)
    assert segments == [(0, 100), (156, 100), (312, 100), (455, 100)]


def test_single_chunk():
    segments = calculate_segments(100, 100)
    assert segments == [(0, 100)]


def test_size_smaller_than_chunk():
    segments = calculate_segments(50, 100)
    assert segments == [(0, 50)]


def test_zero_size():
    segments = calculate_segments(0, 100)
    assert segments == []
