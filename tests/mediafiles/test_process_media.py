import pytest

from xklb.__main__ import library as lb
from xklb.utils import devices


def test_shrink(temp_db, capsys):
    db1 = temp_db()
    lb(["row-add", db1, "--path", "test.mp4", "--duration", "2", "--size", "2000000"])

    with pytest.raises(devices.InteractivePrompt):
        lb(["shrink", db1, "-s", "test.mp4"])
    captured = capsys.readouterr().out
    assert "Video: mp4" in captured.replace("\n", "")
    assert len(captured) > 150
