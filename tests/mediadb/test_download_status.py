import json

from tests.utils import v_db
from library.__main__ import library as lb


def test_download_status(assert_unchanged, capsys):
    lb(["download-status", v_db, "--to-json"])
    captured = capsys.readouterr().out.strip()
    assert_unchanged([json.loads(s) for s in captured.splitlines()])
