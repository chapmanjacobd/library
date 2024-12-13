import pytest

from library.playback.playback_control import from_duration_to_duration_str


@pytest.mark.parametrize(
    ("duration", "segment_start", "segment_end", "expected"),
    [
        (0, 0, 0, "Duration: 0:00"),
        (360, 1000, 0, "Duration: 6:00 (16:40 to 22:40)"),
        (3600, 0, 0, "Duration: 1:00:00"),
        (3600, 0, 3000, "Duration: 50:00 (0:00 to 50:00)"),
        (3600, 1800, 0, "Duration: 30:00 (30:00 to 1:00:00)"),
        (3600, 1800, 3000, "Duration: 20:00 (30:00 to 50:00)"),
        (3600, 3000, 0, "Duration: 10:00 (50:00 to 1:00:00)"),
        (3600, 3000, 2000, "Duration: 16:40 (33:20 to 50:00)"),
    ],
)
def test_from_duration_to_duration_str(duration, segment_start, segment_end, expected):
    result = from_duration_to_duration_str(duration, segment_start, segment_end)
    assert result == expected
