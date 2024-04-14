from pathlib import Path
from subprocess import CalledProcessError
from unittest import skip

import pytest

from xklb.lb import library as lb


@skip("ImageMagick dependency")
def test_incomplete_file(temp_file_tree):
    file_tree = {"file.jpg": "4"}
    src1 = temp_file_tree(file_tree)
    with pytest.raises(CalledProcessError):
        lb(["process-image", str(Path(src1, "file.jpg"))])


@skip("ImageMagick dependency")
def test_incomplete_file_delete(temp_file_tree):
    file_tree = {"file.jpg": "4"}
    src1 = temp_file_tree(file_tree)
    lb(["process-image", "--delete-unplayable", str(Path(src1, "file.jpg"))])
