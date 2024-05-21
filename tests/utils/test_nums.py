import pytest

from xklb.utils import nums, sql_utils


@pytest.mark.parametrize(
    "human,b",
    [
        ("30", 31457280),
        ("30b", 30),
        ("30kb", 30720),
        ("30mb", 31457280),
        ("30gb", 32212254720),
        ("30tb", 32985348833280),
        ("30TiB", 32985348833280),
        ("30TB", 32985348833280),
        ("3.5mb", 3670016),
        ("3.5 mb", 3670016),
        ("3.5 mib", 3670016),
    ],
)
def test_human_to_bytes(human, b):
    assert nums.human_to_bytes(human) == b


@pytest.mark.parametrize(
    "human,b",
    [
        ("30", 30000000),
        ("30bits", 30),
        ("30Kbit", 30000),
        ("30mbps", 30000000),
        ("30gb", 30000000000),
        ("30tb", 30000000000000),
        ("30TiB", 30000000000000),
        ("30TB", 30000000000000),
        ("3.5mb", 3500000),
        ("3.5 mb", 3500000),
        ("3.5 mib", 3500000),
    ],
)
def test_human_to_bits(human, b):
    assert nums.human_to_bytes(human, False) == b


def test_human_to_seconds():
    assert nums.human_to_seconds(None) is None
    assert nums.human_to_seconds("30") == 1800
    assert nums.human_to_seconds("30s") == 30
    assert nums.human_to_seconds("30m") == 1800
    assert nums.human_to_seconds("30mins") == 1800
    assert nums.human_to_seconds("30h") == 3600 * 30
    assert nums.human_to_seconds("30 hour") == 3600 * 30
    assert nums.human_to_seconds("30hours") == 3600 * 30
    assert nums.human_to_seconds("1 week") == 86400 * 7
    assert nums.human_to_seconds("30d") == 86400 * 30
    assert nums.human_to_seconds("30 days") == 86400 * 30
    assert nums.human_to_seconds("3.5mo") == 9072000
    assert nums.human_to_seconds("3.5months") == 9072000
    assert nums.human_to_seconds("3.5 years") == 110376000
    assert nums.human_to_seconds("3.5y") == 110376000


@pytest.mark.parametrize(
    "input_sizes,s",
    [
        (["<10MB"], "and size < 10485760 "),
        ([">100KB", "<10MB"], "and size > 102400 and size < 10485760 "),
        (["+100KB"], "and size >= 102400 "),
        (["-10MB"], "and 10485760 >= size "),
        (["100KB%10"], "and 92160 <= size and size <= 112640 "),
        (["100KB"], "and 102400 = size "),
    ],
)
def test_parse_size(input_sizes, s):
    result = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", input_sizes)
    assert result == s, f"Expected {s}, but got {result}"


def test_parse_duration():
    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["<30s"])
    expected_result = "and duration < 30 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", [">1min", "<30s"])
    expected_result = "and duration > 60 and duration < 30 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["+1min"])
    expected_result = "and duration >= 60 "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["-30s"])
    expected_result = "and 30 >= duration "
    assert result == expected_result

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["1min%10"])
    expected_result = "and 66 >= duration and duration >= 54 "

    result = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", ["1min"])
    expected_result = "and 60 = duration "

    assert result == expected_result


def scan_stats(scans, scan_duration):
    return (
        len(scans),  # number of scans
        scan_duration,  # duration of media scanned
        len(scans) * scan_duration,  # total scanned time
        0 if len(scans) == 1 else scans[1] - scan_duration,  # first gap time
    )


def test_calculate_segments():
    assert nums.calculate_segments(100, 25) == [0, 35, 75]
    assert nums.calculate_segments(1000, 100) == [0, 200, 400, 600, 900]
    assert nums.calculate_segments(1000, 100, 0.5) == [0, 600, 900]

    # small_file
    assert nums.calculate_segments(30, 25) == [0]

    # zero_size
    assert nums.calculate_segments(0, 25) == []

    # big_gap
    assert nums.calculate_segments(100, 25, 0.9) == [0, 75]

    # medium_gap
    assert nums.calculate_segments(100, 25, 0.2) == [0, 45, 75]

    # small_gap
    assert nums.calculate_segments(100, 25, 0.01) == [0, 26, 75]

    # bytes
    assert nums.calculate_segments(1024, 256, 512) == [0, 768]
    assert nums.calculate_segments(555, 100) == [0, 156, 312, 455]
    assert nums.calculate_segments(100, 100) == [0]
    assert nums.calculate_segments(50, 100) == [0]

    result = [scan_stats(nums.calculate_segments(5 * 60, 3, 50 - percent), 3) for percent in [10, 20, 30, 40, 45]]
    assert result == [(8, 3, 24, 40), (10, 3, 30, 30), (14, 3, 42, 20), (24, 3, 72, 10), (38, 3, 114, 5)]
