import json
from tests.utils import v_db
from xklb.__main__ import library as lb


def test_download_status(assert_unchanged, capsys):
    lb(["download-status", v_db, "--to-json"])
    captured = capsys.readouterr().out
    assert_unchanged(json.loads(captured))
