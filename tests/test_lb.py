import os.path, sys
from pathlib import Path

import pytest

from library.__main__ import NESTED_COMMANDS, _canonical_nested_paths
from library.__main__ import library as lb
from library.__main__ import modules
from tests.utils import p

subcommands = [
    path
    for group, command_tree in NESTED_COMMANDS.items()
    for path in _canonical_nested_paths(group, command_tree)
]
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
        lb([*subcommand.split(), "-h"])
    captured = capsys.readouterr().out.replace("\n", "")
    first_tokens = " ".join(subcommand.split()[:2])
    assert f"usage: library {first_tokens}" in captured


def get_test_name(s):
    path = s.replace("library.", "tests.", 1).replace(".", os.sep)
    parent, name = os.path.split(path)
    path = os.path.join(parent, "test_" + name + ".py")
    return path


@pytest.mark.parametrize("path", [get_test_name(s) for s in unique_modules])
def test_pytest_files_exist(path):
    Path(path).touch(exist_ok=True)
    if p(path) not in (  # TODOs
        p("tests/files/test_christen.py"),
        p("tests/folders/test_big_dirs.py"),
        p("tests/multidb/test_copy_play_counts.py"),
        p("tests/misc/test_dedupe_czkawka.py"),
        p("tests/files/test_similar_files.py"),
        p("tests/folders/test_move_list.py"),
        p("tests/mediadb/test_history_add.py"),
        p("tests/mediadb/test_history.py"),
        p("tests/mediadb/test_redownload.py"),
        p("tests/playback/test_playback_control.py"),
        p("tests/folders/test_mount_stats.py"),
        p("tests/mediadb/test_block.py"),
        p("tests/mediadb/test_optimize_db.py"),
        p("tests/misc/test_export_text.py"),
    ):
        assert os.path.getsize(path) > 0, f"Pytest file {path} is empty."
