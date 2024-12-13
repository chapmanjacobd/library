import json

from tests.utils import v_db
from library.__main__ import library as lb
from library.utils import consts

platform = "linux"
if consts.IS_WINDOWS:
    platform = "windows"
elif consts.IS_MAC:
    platform = "mac"


def test_disk_usage(assert_unchanged, capsys):
    lb(["du", v_db, "--to-json"])
    captured = capsys.readouterr().out
    assert_unchanged(
        [json.loads(line) for line in captured.strip().split("\n")], basename=f"test_disk_usage.{platform}"
    )
