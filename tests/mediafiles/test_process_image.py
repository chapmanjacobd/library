import shutil, tempfile
from pathlib import Path
from shutil import which

import pytest

from library.__main__ import library as lb
from library.mediafiles.process_image import process_path
from library.utils import arggroups, objects, processes
from tests.utils import get_default_args


def test_web_url(capsys):
    url = "http://everythingthathappened.today/september/assets/images/18-4.jpg"
    lb(["process-image", "--simulate", url])
    captured = capsys.readouterr().out
    assert url in captured


def test_delete_original_keeps_successful_larger_transcode(temp_file_tree, monkeypatch):
    source_path = Path(temp_file_tree({"source.jpg": "source"}), "source.jpg")
    output_path = source_path.with_suffix(".avif")
    args = objects.NoneSpace(
        delete_larger=True,
        delete_original=True,
        max_image_width=2400,
        max_image_height=2400,
        simulate=False,
    )
    monkeypatch.setattr("library.mediafiles.process_image.web.gen_output_path", lambda *_args, **_kwargs: output_path)
    monkeypatch.setattr(
        "library.mediafiles.process_image.devices.clobber",
        lambda _args, source, output: (source, output),
    )
    monkeypatch.setattr(
        "library.mediafiles.process_image.processes.cmd",
        lambda *_args, **_kwargs: output_path.write_text("larger transcode"),
    )

    result = process_path(args, source_path)

    assert result == str(output_path)
    assert not source_path.exists()
    assert output_path.exists()


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
    except Exception as excinfo:
        print(excinfo)


@pytest.mark.skipif(not which("magick"), reason="requires magick")
def test_incomplete_file_delete(temp_file_tree):
    file_tree = {"file.jpg": "4"}
    src1 = temp_file_tree(file_tree)
    lb(["process-image", "--delete-unplayable", str(Path(src1, "file.jpg"))])
