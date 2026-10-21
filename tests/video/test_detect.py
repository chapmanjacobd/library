import sys
from types import SimpleNamespace

import numpy as np
import pytest

from library.video import detect


@pytest.mark.parametrize("flag", ["--still-image", "--static-image", "--image", "--freeze-frame"])
def test_detection_mode_aliases_select_still_image(monkeypatch, flag):
    monkeypatch.setattr("sys.argv", ["detect", flag, "video.mp4"])

    args = detect.parse_args()

    assert args.still_image == detect.FreezeSpec(ratio=0.95)
    assert args.paths == ["video.mp4"]


def test_freeze_frame_accepts_duration(monkeypatch):
    monkeypatch.setattr("sys.argv", ["detect", "--freeze-frame", "10s", "video.mp4"])

    args = detect.parse_args()

    assert args.still_image == detect.FreezeSpec(duration=10)


def test_detection_mode_is_required(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["detect", "video.mp4"])

    with pytest.raises(SystemExit):
        detect.parse_args()


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("--black", True),
        ("--blank", True),
        ("--no-black", False),
        ("--no-blank", False),
    ],
)
def test_blank_frame_aliases(monkeypatch, flag, expected):
    monkeypatch.setattr("sys.argv", ["detect", flag, "video.mp4"])

    args = detect.parse_args()

    assert args.black is expected


def test_metadata_filters_parse_existing_comparison_convention(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "detect",
            "--fps=-24",
            "--resolution=-1920x+1080",
            "--aspect-ratio=16:9",
            "video.mp4",
        ],
    )

    args = detect.parse_args()

    assert args.fps == detect.Comparison("<=", 24)
    assert args.resolution == (detect.Comparison("<=", 1920), detect.Comparison(">=", 1080))
    assert args.aspect_ratio == detect.Comparison("=", 16 / 9, 0.01)


def test_metadata_filters_match_video_stream(monkeypatch):
    probe = SimpleNamespace(
        fps=24,
        video_streams=[{"width": 1920, "height": 1080, "display_aspect_ratio": "16:9"}],
    )
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    args = SimpleNamespace(
        fps=detect.Comparison("<=", 24),
        resolution=(detect.Comparison("<=", 1920), detect.Comparison(">=", 1080)),
        width=None,
        height=None,
        aspect_ratio=detect.Comparison("=", 16 / 9, 0.01),
    )

    assert detect.matches_metadata_filters("video.mp4", args) is True


def test_blank_frame_detection_stops_on_match(monkeypatch):
    probe = SimpleNamespace(has_video=True, duration=10)
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    monkeypatch.setattr(detect, "_sample_frame", lambda _path, _timestamp: np.zeros(160 * 160, dtype=np.uint8))

    assert detect.has_blank_frame("video.mp4")


def test_freeze_frame_detection_stops_when_ratio_is_reached(monkeypatch):
    probe = SimpleNamespace(has_video=True, duration=10)
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    calls = []
    monkeypatch.setattr(
        detect,
        "_sample_frame",
        lambda _path, timestamp: calls.append(timestamp) or np.zeros(160 * 160, dtype=np.uint8),
    )

    assert detect.has_freeze_frame("video.mp4", detect.FreezeSpec(ratio=0.95))
    assert len(calls) < detect.MAX_FREEZE_SAMPLE_INTERVALS + 1


def test_freeze_frame_duration_uses_ffmpeg_freezedetect(monkeypatch):
    probe = SimpleNamespace(has_video=True, duration=60)
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    monkeypatch.setattr(
        detect.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr="freeze_duration: 10.0"),
    )

    assert detect.has_freeze_frame("video.mp4", detect.FreezeSpec(duration=10))


def test_static_image_detection_compares_sampled_frames(monkeypatch):
    probe = SimpleNamespace(has_video=True, duration=10)
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    monkeypatch.setattr(detect, "_sample_frame", lambda _path, _timestamp: np.zeros(160 * 160, dtype=np.uint8))

    assert detect.is_still_image("video.mp4")


def test_static_image_detection_rejects_changing_frames(monkeypatch):
    probe = SimpleNamespace(has_video=True, duration=10)
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    frames = iter(
        [
            np.zeros(160 * 160, dtype=np.uint8),
            np.ones(160 * 160, dtype=np.uint8) * 255,
            np.zeros(160 * 160, dtype=np.uint8),
            np.ones(160 * 160, dtype=np.uint8) * 255,
            np.zeros(160 * 160, dtype=np.uint8),
        ]
    )
    monkeypatch.setattr(detect, "_sample_frame", lambda _path, _timestamp: next(frames))

    assert not detect.is_still_image("video.mp4")
