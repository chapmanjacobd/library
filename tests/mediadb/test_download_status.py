import json

from library.__main__ import library as lb
from tests.utils import v_db


def test_download_status(assert_unchanged, capsys):
    lb(["download-status", v_db, "--to-json"])
    captured = capsys.readouterr().out.strip()
    assert_unchanged([json.loads(s) for s in captured.splitlines()])
