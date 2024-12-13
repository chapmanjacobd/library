from pathlib import Path

from library.__main__ import library as lb
from tests.utils import v_db


def test_stats(capsys):
    lb(["history-add", v_db, str(Path("tests/data/test.gif"))])
    lb(["stats", v_db])
    captured = capsys.readouterr().out
    assert "total_size" in captured.replace("\n", "")
    assert len(captured) > 100
