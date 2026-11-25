import argparse
import shlex
import tempfile
from pathlib import Path
from shutil import which

import pytest

from library.__main__ import library as lb
from library.shrink.process_text import _package_epub
from library.utils import nums, path_utils


def test_package_epub_passes_output_profile_as_two_arguments(capsys):
    args = argparse.Namespace(simulate=True)

    _package_epub(args, Path("book.opf"), Path("book.epub"), Path("style.css"))

    command = shlex.split(capsys.readouterr().out)
    assert command[command.index("--output-profile") + 1] == "tablet"


@pytest.mark.skipif(not which("calibre"), reason="requires calibre")
def test_process_text_too_small():
    temp_dir = tempfile.TemporaryDirectory()

    lb(["process-text", f"--prefix={temp_dir.name}", "https://www.gutenberg.org/cache/epub/844/pg844.txt"])

    assert path_utils.folder_size(temp_dir.name) < nums.human_to_bytes("163Ki")
    # TODO: add test for large enough source file

    try:
        temp_dir.cleanup()
    except Exception as excinfo:
        print(excinfo)
