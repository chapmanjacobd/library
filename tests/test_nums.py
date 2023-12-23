from xklb.utils import nums
from xklb.utils.nums import calculate_segments


def test_calculate_segments():
    assert calculate_segments(100, 25) == [(0, 25), (35, 25), (75, 25)]
    assert calculate_segments(1000, 100) == [(0, 100), (200, 100), (400, 100), (600, 100), (900, 100)]
    assert calculate_segments(1000, 100, 0.5) == [(0, 100), (600, 100), (900, 100)]

    # small_file
    assert calculate_segments(30, 25) == [(0, 30)]

    # zero_size
    assert calculate_segments(0, 25) == []

    # big_gap
    assert calculate_segments(100, 25, 0.9) == [(0, 25), (75, 25)]

    # medium_gap
    assert calculate_segments(100, 25, 0.2) == [(0, 25), (45, 25), (75, 25)]

    # small_gap
    assert calculate_segments(100, 25, 0.01) == [(0, 25), (26, 25), (75, 25)]

    # bytes
    assert calculate_segments(1024, 256, 512) == [(0, 256), (768, 256)]
    assert calculate_segments(555, 100) == [(0, 100), (156, 100), (312, 100), (455, 100)]
    assert calculate_segments(100, 100) == [(0, 100)]
    assert calculate_segments(50, 100) == [(0, 50)]

    # TODO: replicate something like the scan_stats(*nums.cover_scan test

def scan_stats(scans, scan_duration):
    return (
        len(scans),  # number of scans
        scan_duration,  # duration of media scanned
        len(scans) * scan_duration,  # total scanned time
        0 if len(scans) == 1 else scans[1] - scan_duration,  # first gap time
    )


def test_cover_scan():
    assert scan_stats(*nums.cover_scan(1, 0.01)) == (1, 1, 1, 0)
    assert scan_stats(*nums.cover_scan(1, 100)) == (1, 1, 1, 0)

    result = [scan_stats(*nums.cover_scan(5 * 60, percent)) for percent in [5, 10, 20, 30]]
    assert result == [(3, 7, 21, 143), (6, 6, 36, 54), (12, 5, 60, 22), (18, 5, 90, 12)]

    result = [scan_stats(*nums.cover_scan(2 * 60 * 60, percent)) for percent in [5, 10, 20, 30]]
    assert result == [(5, 90, 450, 1710), (9, 90, 810, 810), (18, 84, 1512, 339), (27, 83, 2241, 193)]
