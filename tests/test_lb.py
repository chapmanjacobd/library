import sys

import pytest

from xklb.lb import library as lb, progs
from xklb.utils.log_utils import log

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


def test_duplicate_args(capsys):
    for _, category_progs in progs.items():
        for subcommand, _ in category_progs.items():
            with pytest.raises(SystemExit):
                lb([subcommand, '-h'])
            captured = capsys.readouterr().out.replace("\n", "")
            assert f'usage: library {subcommand.replace("_", "-")}' in captured

            log.info(len(captured))
