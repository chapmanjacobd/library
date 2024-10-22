import tempfile
from shutil import which

import pytest

from xklb.__main__ import library as lb
from xklb.utils import nums, path_utils, strings


@pytest.mark.skipif(not which("calibre"), reason="requires calibre")
def test_process_text_too_small():
    temp_dir = tempfile.TemporaryDirectory()

    lb(
        [
            "process-text",
            f"--prefix={temp_dir.name}",
            "https://www.globalgreyebooks.com/ebooks1/oscar-wilde/importance-of-being-earnest/importance-of-being-earnest.mobi",
        ]
    )

    assert path_utils.folder_size(temp_dir.name) < nums.human_to_bytes('163Ki')
    # TODO: add test for large enough source file

    try:
        temp_dir.cleanup()
    except Exception as e:
        print(e)
