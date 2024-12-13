from tests.utils import v_db
from library.__main__ import library as lb


def test_search_db(capsys):
    lb(["sdb", v_db, "media", "test.gif"])
    captured = capsys.readouterr().out
    assert "image/gif" in captured.replace("\n", "")
    assert len(captured) > 150
