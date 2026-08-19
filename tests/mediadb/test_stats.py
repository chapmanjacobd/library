import sys
from pathlib import Path
from unittest import mock

from library.__main__ import library as lb
from library.mediadb import stats
from tests.utils import v_db


def test_stats(capsys):
    lb(["history-add", v_db, str(Path("tests/data/test.gif"))])
    lb(["stats", v_db])
    captured = capsys.readouterr().out
    assert "total_size" in captured.replace("\n", "")
    assert len(captured) > 100


def test_deleted_stats_include_deleted_media_by_default():
    with mock.patch.object(sys, "argv", ["stats", v_db, "time_deleted"]):
        args = stats.parse_args()

    assert args.hide_deleted is False
    assert not any("COALESCE(m.time_deleted,0) = 0" in condition for condition in args.filter_sql)
