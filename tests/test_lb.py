import os.path, sys

import pytest

from xklb.lb import library as lb
from xklb.lb import modules, progs
from xklb.utils import iterables

subcommands = list(iterables.flatten((v.keys() for _, v in progs.items())))
unique_modules = list(set(s.rsplit(".", 1)[0] for s in modules.keys()))  # chop off function names


def test_lb_help(capsys):
    sys.argv = ["lb"]
    with pytest.raises(SystemExit):
        lb(None)
    captured = capsys.readouterr().out
    assert "subcommands" in captured

    with pytest.raises(SystemExit):
        lb(["-h"])
    captured = capsys.readouterr().out
    assert "subcommands" in captured


@pytest.mark.parametrize("subcommand", subcommands)
def test_usage(capsys, subcommand):
    with pytest.raises(SystemExit):
        lb([subcommand, "-h"])
    captured = capsys.readouterr().out.replace("\n", "")
    assert f'usage: library {subcommand.replace("_", "-")}' in captured


def get_test_name(s):
    path = s.replace("xklb.", "tests.", 1).replace(".", "/")
    parent, name = os.path.split(path)
    path = os.path.join(parent, "test_" + name + ".py")
    return path


"""
@pytest.mark.parametrize("path", [get_test_name(s) for s in unique_modules])
def test_pytest_files_exist(path):
    Path(path).touch(exist_ok=True)
    assert os.path.getsize(path) > 0, f"Pytest file {path} is empty."
"""
