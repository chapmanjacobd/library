import os.path, sys
from pathlib import Path

import pytest

from tests.utils import p
from xklb.lb import library as lb
from xklb.lb import modules, progs
from xklb.utils import iterables

subcommands = list(iterables.flatten((v.keys() for _, v in progs.items())))
unique_modules = list(set(s.rsplit(".", 1)[0] for s in modules.keys()))  # chop off function names


def test_lb_help(capsys):
    sys.argv = ["lb"]
    with pytest.raises(SystemExit):
        lb(None)
    captured = capsys.readouterr().out.replace("\n", "")
    assert "subcommands" in captured

    with pytest.raises(SystemExit):
        lb(["-h"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert "subcommands" in captured


@pytest.mark.parametrize("subcommand", subcommands)
def test_usage(capsys, subcommand):
    with pytest.raises(SystemExit):
        lb([subcommand, "-h"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert f'usage: library {subcommand.replace("_", "-")}' in captured


def get_test_name(s):
    path = s.replace("xklb.", "tests.", 1).replace(".", os.sep)
    parent, name = os.path.split(path)
    path = os.path.join(parent, "test_" + name + ".py")
    return path


@pytest.mark.parametrize("path", [get_test_name(s) for s in unique_modules])
def test_pytest_files_exist(path):
    Path(path).touch(exist_ok=True)
    if p(path) not in (
        p("tests/files/test_christen.py"),
        p("tests/files/test_sample_compare.py"),
        p("tests/files/test_sample_hash.py"),
        p("tests/files/test_similar_files.py"),
        p("tests/folders/test_big_dirs.py"),
        p("tests/folders/test_mount_stats.py"),
        p("tests/folders/test_move_list.py"),
        p("tests/fsdb/test_disk_usage.py"),
        p("tests/fsdb/test_search_db.py"),
        p("tests/mediadb/test_block.py"),
        p("tests/mediadb/test_download_status.py"),
        p("tests/mediadb/test_history_add.py"),
        p("tests/mediadb/test_history.py"),
        p("tests/mediadb/test_optimize_db.py"),
        p("tests/mediadb/test_redownload.py"),
        p("tests/mediadb/test_search.py"),
        p("tests/mediadb/test_stats.py"),
        p("tests/misc/test_dedupe_czkawka.py"),
        p("tests/misc/test_export_text.py"),
        p("tests/multidb/test_copy_play_counts.py"),
        p("tests/multidb/test_merge_dbs.py"),
        p("tests/playback/test_playback_control.py"),
        p("tests/playback/test_surf.py"),  # TODO: remove one line when you see this
    ):
        assert os.path.getsize(path) > 0, f"Pytest file {path} is empty."
