from tests.utils import v_db
from xklb.__main__ import library as lb

def test_stats(capsys):
    lb(["stats", v_db])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "duration" in captured
    assert len(captured) > 150
