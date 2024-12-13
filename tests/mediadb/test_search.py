from library.__main__ import library as lb
from tests.utils import v_db


def test_search(capsys):
    lb(["search", v_db])
    captured = capsys.readouterr().out
    assert "end" in captured.replace("\n", "")
    assert len(captured) > 150
