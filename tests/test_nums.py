from xklb.utils import nums
from xklb.utils.nums import calculate_segments


def test_calculate_segments():
    assert calculate_segments(100, 25) == [0, 35, 75]
    assert calculate_segments(1000, 100) == [0, 200, 400, 600, 900]
    assert calculate_segments(1000, 100, 0.5) == [0, 600, 900]

    # small_file
    assert calculate_segments(30, 25) == [0]

    # zero_size
    assert calculate_segments(0, 25) == []

    # big_gap
    assert calculate_segments(100, 25, 0.9) == [0, 75]

    # medium_gap
    assert calculate_segments(100, 25, 0.2) == [0,45,75]

    # small_gap
    assert calculate_segments(100, 25, 0.01) == [0, 26, 75]

    # bytes
    assert calculate_segments(1024, 256, 512) == [0, 768]
    assert calculate_segments(555, 100) == [0, 156, 312, 455]
    assert calculate_segments(100, 100) == [0]
    assert calculate_segments(50, 100) == [0]

    result = [scan_stats(nums.calculate_segments(5 * 60, 3, 50-percent), 3 ) for percent in [10, 20, 30, 40, 45]]
    assert result == [(8, 3, 24, 40), (10, 3, 30, 30), (14, 3, 42, 20), (24, 3, 72, 10), (38, 3, 114, 5)]

def scan_stats(scans, scan_duration):
    return (
        len(scans),  # number of scans
        scan_duration,  # duration of media scanned
        len(scans) * scan_duration,  # total scanned time
        0 if len(scans) == 1 else scans[1] - scan_duration,  # first gap time
    )
