import shutil, tempfile
from pathlib import Path
from shutil import which

import pytest

from library.__main__ import library as lb


@pytest.mark.skipif(not which("magick"), reason="requires magick")
def test_process_image():
    temp_dir = tempfile.TemporaryDirectory()
    input_path1 = shutil.copy("tests/data/test_frame.gif", temp_dir.name)
    input_path2 = shutil.copy("tests/data/test.gif", temp_dir.name)

    output_path = Path(temp_dir.name, "output.pdf")

    lb(["images-to-pdf", input_path1, input_path2, "--output-path", str(output_path)])

    output_stats = output_path.stat()
    assert output_stats.st_size >= 9999

    try:
        temp_dir.cleanup()
    except Exception as excinfo:
        print(excinfo)
