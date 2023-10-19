import sys

import pytest

from xklb.lb import library as lb
from xklb.play_actions import watch as wt


def test_lb_help(capsys):
    lb_help_text = "local media:,online media:".split(",")
    sys.argv = ["lb"]
    with pytest.raises(SystemExit):
        lb(None)
    captured = capsys.readouterr().out
    for help_text in lb_help_text:
        assert help_text in captured

    with pytest.raises(SystemExit):
        lb(["-h"])
    captured = capsys.readouterr().out
    for help_text in lb_help_text:
        assert help_text in captured


def test_wt_help(capsys):
    wt_help_text = "usage:,where,sort,--duration".split(",")

    sys.argv = ["wt", "-h"]
    with pytest.raises(SystemExit):
        wt()
    captured = capsys.readouterr().out.replace("\n", "")
    for help_text in wt_help_text:
        assert help_text in captured

    with pytest.raises(SystemExit):
        lb(["wt", "-h"])
    captured = capsys.readouterr().out.replace("\n", "")
    for help_text in wt_help_text:
        assert help_text in captured
