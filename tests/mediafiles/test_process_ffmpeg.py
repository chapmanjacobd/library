import shutil, tempfile
from pathlib import Path
from shutil import which

import pytest

from tests.utils import get_default_args
from xklb.__main__ import library as lb
from xklb.mediafiles.process_ffmpeg import is_animation_from_probe, process_path
from xklb.utils import arggroups, objects, processes


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

    assert Path(output_path).suffix == out_ext

    out_probe = processes.FFProbe(output_path)
    assert out_probe.duration == duration

    try:
        temp_dir.cleanup()
    except Exception as e:
        print(e)
