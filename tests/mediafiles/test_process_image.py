import shutil, tempfile
from pathlib import Path
from shutil import which

import pytest

from tests.utils import get_default_args
from xklb.__main__ import library as lb
from xklb.mediafiles.process_image import process_path
from xklb.utils import arggroups, objects, processes


def test_web_url(capsys):
    url = "http://everythingthathappened.today/september/assets/images/18-4.jpg"
    lb(["process-image", "--simulate", url])
    captured = capsys.readouterr().out
    assert url in captured


@pytest.mark.skipif(not which("magick"), reason="requires magick")
def test_process_image():
    temp_dir = tempfile.TemporaryDirectory()
    input_path = shutil.copy("tests/data/test_frame.gif", temp_dir.name)

    args = objects.NoneSpace(**get_default_args(arggroups.clobber, arggroups.process_ffmpeg))
    output_path = process_path(args, input_path)

    assert output_path is not None
    assert Path(output_path).suffix == ".avif"

    out_probe = processes.FFProbe(output_path)
    assert out_probe.video_streams[0]["codec_name"] == "av1"

    try:
        temp_dir.cleanup()
    except Exception as e:
        print(e)


@pytest.mark.skipif(not which("magick"), reason="requires magick")
def test_incomplete_file_delete(temp_file_tree):
    file_tree = {"file.jpg": "4"}
    src1 = temp_file_tree(file_tree)
    lb(["process-image", "--delete-unplayable", str(Path(src1, "file.jpg"))])
