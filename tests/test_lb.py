import sys
from pathlib import Path

import pytest

from library.__main__ import library as lb
from library.__main__ import (
    _canonical_nested_paths_for_all_groups,
    _canonical_target_paths,
    _nested_target,
    modules,
)

subcommands = _canonical_nested_paths_for_all_groups()
unique_modules = sorted({s.rsplit(".", 1)[0] for s in modules})


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

    usage = capsys.readouterr().out.splitlines()[0]
    assert usage.startswith("usage: library")
    target, _consumed = _nested_target(subcommand.split())
    canonical_path = _canonical_target_paths().get(target, subcommand)
    assert canonical_path in usage


def get_test_name(s):
    path = Path(s.replace("library.", "tests.", 1).replace(".", "/"))
    return path.parent / f"test_{path.name}.py"


@pytest.mark.parametrize("path", [get_test_name(s) for s in unique_modules])
def test_pytest_files_exist(path):
    assert path.is_file(), f"Missing pytest file {path}."
    assert path.stat().st_size > 0, f"Pytest file {path} is empty."
