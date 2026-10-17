import pytest

from library.playback import playback_control
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


@pytest.mark.parametrize(
    ("command", "expected_catt_command"),
    [("rewind", "rewind"), ("ffwd", "ffwd")],
)
def test_directional_playback_aliases_apply_direction(monkeypatch, command, expected_catt_command):
    monkeypatch.setattr(playback_control, "_now_playing", lambda _args: {"catt": "playing", "mpv": None})
    commands = []
    monkeypatch.setattr(playback_control.processes, "cmd", lambda *args: commands.append(args))
    monkeypatch.setattr("sys.argv", [f"library {command}", "5"])

    getattr(playback_control, f"playback_{command}")()

    expected_seconds = "-5" if command == "rewind" else "5"
    assert commands == [("catt", expected_catt_command, expected_seconds)]
