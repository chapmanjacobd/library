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


def test_detection_durations_parse_milliseconds(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "detect",
            "--black",
            "--black-detect-duration",
            "1.2s",
            "--blank",
            "--blank-detect-duration",
            "250ms",
            "video.mp4",
        ],
    )

    args = detect.parse_args()

    assert args.black_detect_duration == 1.2
    assert args.blank_detect_duration == 0.25


def test_detection_mode_is_required(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["detect", "video.mp4"])

    with pytest.raises(SystemExit):
        detect.parse_args()


@pytest.mark.parametrize(
    ("flag", "attribute"),
    [
        ("--black", "black"),
        ("--blank", "blank"),
        ("--no-black", "black"),
        ("--no-blank", "blank"),
    ],
)
def test_black_and_blank_flags(monkeypatch, flag, attribute):
    monkeypatch.setattr("sys.argv", ["detect", flag, "video.mp4"])

    args = detect.parse_args()

    expected = not flag.startswith("--no-")
    assert getattr(args, attribute) is expected


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
    probe = SimpleNamespace(
        has_video=True,
        duration=1,
        fps=10,
        video_streams=[{"width": 160, "height": 160}],
    )
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    monkeypatch.setattr(
        detect,
        "_iter_sampled_frames",
        lambda _path, _duration, _intervals: (
            frame for frame in [np.zeros(detect.FRAME_BYTES, dtype=np.uint8)] * 11
        ),
    )

    assert detect.has_blank_frame("video.mp4")


def test_combined_full_frame_filters_share_one_frame_stream(monkeypatch):
    probe = SimpleNamespace(
        has_video=True,
        duration=1,
        fps=10,
        video_streams=[{"width": 160, "height": 160}],
    )
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    calls = []

    def sampled_frames(_path, _duration, intervals):
        calls.append(intervals)
        for _ in range(intervals + 1):
            yield np.zeros(detect.FRAME_BYTES, dtype=np.uint8)

    monkeypatch.setattr(detect, "_iter_sampled_frames", sampled_frames)

    assert detect._matches_full_frame_filters(  # noqa: SLF001
        "video.mp4",
        detect.FreezeSpec(ratio=0.5),
        blank=True,
        blank_duration=0.8,
        samples=2,
        threshold=1,
    )
    assert calls == [10]


def test_black_frame_detection_uses_blackdetect(monkeypatch):
    probe = SimpleNamespace(
        has_video=True,
        duration=10,
    )
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    calls = []
    monkeypatch.setattr(
        detect.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command)
        or SimpleNamespace(returncode=0, stderr="black_start:1 black_duration:0.1"),
    )

    assert detect.has_black_frame("video.mp4")
    assert "blackdetect=d=0.800000000:pix_th=0.1" in calls[0]


def test_freeze_frame_detection_stops_when_ratio_is_reached(monkeypatch):
    probe = SimpleNamespace(has_video=True, duration=10)
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    calls = []

    def sampled_frames(_path, _duration, intervals):
        for _ in range(intervals + 1):
            calls.append(True)
            yield np.zeros(detect.FRAME_BYTES, dtype=np.uint8)

    monkeypatch.setattr(
        detect,
        "_iter_sampled_frames",
        sampled_frames,
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
    monkeypatch.setattr(
        detect,
        "_iter_sampled_frames",
        lambda _path, _duration, _intervals: (
            frame for frame in [np.zeros(detect.FRAME_BYTES, dtype=np.uint8)] * 6
        ),
    )

    assert detect.is_still_image("video.mp4")


def test_static_image_detection_rejects_changing_frames(monkeypatch):
    probe = SimpleNamespace(has_video=True, duration=10)
    monkeypatch.setattr(detect.processes, "FFProbe", lambda _path: probe)
    frames = (
        [
            np.zeros(detect.FRAME_BYTES, dtype=np.uint8),
            np.ones(detect.FRAME_BYTES, dtype=np.uint8) * 255,
            np.zeros(detect.FRAME_BYTES, dtype=np.uint8),
            np.ones(detect.FRAME_BYTES, dtype=np.uint8) * 255,
            np.zeros(detect.FRAME_BYTES, dtype=np.uint8),
            np.ones(detect.FRAME_BYTES, dtype=np.uint8) * 255,
        ]
    )
    frames = (frame for frame in frames)
    monkeypatch.setattr(
        detect,
        "_iter_sampled_frames",
        lambda _path, _duration, _intervals: frames,
    )

    assert not detect.is_still_image("video.mp4")
