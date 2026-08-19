import shutil, tempfile
from pathlib import Path
from shutil import which
from types import SimpleNamespace

import pytest

from library.__main__ import library as lb
from library.mediafiles import process_ffmpeg
from library.mediafiles.process_ffmpeg import is_animation_from_probe, process_path
from library.utils import arggroups, objects, processes
from tests.utils import get_default_args


@pytest.mark.parametrize(
    ("path", "result"),
    [
        ("tests/data/test.gif", True),
        ("tests/data/test.mp4", True),
        ("tests/data/test_frame.gif", False),
    ],
)
def test_probe_if_animation(path, result):
    probe = processes.FFProbe(path)
    assert is_animation_from_probe(probe) is result


def test_web_url(capsys):
    url = "http://example.com/test.m4v"
    lb(["process-ffmpeg", "--simulate", url])
    captured = capsys.readouterr().out
    assert url in captured


def test_process_ffmpeg_returns_all_split_outputs_in_target_directory(monkeypatch, tmp_path):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"x" * 1_000)
    target_directory = tmp_path / "target"

    args = objects.NoneSpace(**get_default_args(arggroups.clobber, arggroups.process_ffmpeg))
    args.always_split = True
    args.min_split_segment = 0.5
    args.delete_larger = False
    args.delete_original = False
    args.verbose = 0

    input_probe = SimpleNamespace(
        streams=[{"index": 0}],
        video_streams=[],
        audio_streams=[
            {
                "index": 0,
                "codec_name": "mp3",
                "channels": 2,
                "bit_rate": 128_000,
                "sample_rate": 44_100,
                "duration": 2,
            }
        ],
        subtitle_streams=[],
        album_art_streams=[],
        format={"duration": 2, "bit_rate": 128_000},
        duration=2,
        fps=None,
    )
    output_probe = SimpleNamespace(streams=[{"index": 0}], duration=1)

    monkeypatch.setattr(
        process_ffmpeg.web,
        "gen_output_path",
        lambda *_args, **_kwargs: target_directory / "renamed.XXXXXXX",
    )
    monkeypatch.setattr(
        process_ffmpeg.processes,
        "FFProbe",
        lambda path: input_probe if Path(path) == source else output_probe,
    )
    monkeypatch.setattr(
        process_ffmpeg.subprocess,
        "check_output",
        lambda *_args, **_kwargs: b"lavfi.silence_start=1.0\n",
    )

    def create_segment_outputs(*command, **_kwargs):
        template = Path(command[-1])
        for index in range(2):
            output = template.with_name(template.name.replace("%03d", f"{index:03d}"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"x")

    monkeypatch.setattr(process_ffmpeg.processes, "cmd", create_segment_outputs)

    result = process_path(args, source)

    assert result == [
        str(target_directory / "renamed.000.mka"),
        str(target_directory / "renamed.001.mka"),
    ]


@pytest.mark.skipif(not which("magick"), reason="requires magick")
@pytest.mark.parametrize(
    ("path", "duration", "out_ext"),
    [
        # ("tests/data/test.gif", 0.6, ".mkv"),
        ("tests/data/test_frame.gif", None, ".avif"),
        # ('tests/data/test.mp4', 12.0, '.mkv'),
    ],
)
def test_process_ffmpeg(path, duration, out_ext):
    temp_dir = tempfile.TemporaryDirectory()
    input_path = shutil.copy(path, temp_dir.name)

    args = objects.NoneSpace(**get_default_args(arggroups.clobber, arggroups.process_ffmpeg))
    output_path = process_path(args, input_path)

    assert output_path is not None
    assert Path(output_path).suffix == out_ext

    out_probe = processes.FFProbe(output_path)
    assert out_probe.duration == duration

    try:
        temp_dir.cleanup()
    except Exception as excinfo:
        print(excinfo)
