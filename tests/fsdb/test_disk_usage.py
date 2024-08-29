import json
from tests.utils import v_db
from xklb.__main__ import library as lb

def test_disk_usage(assert_unchanged, capsys):
    lb(["du", v_db, "--to-json"])
    captured = capsys.readouterr().out
    assert_unchanged([json.loads(line) for line in captured.strip().split('\n')])
