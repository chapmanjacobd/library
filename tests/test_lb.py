import sys
from unittest.mock import patch

from xklb.fs_actions import listen as lt
from xklb.fs_actions import watch as wt
from xklb.lb import lb


def test_lb_args():
    lb(["watch", "test"])
    lb(["listen", "-p"])
    lb([])

    sys.argv = ["lb", "watch", "--sort", "random"]
    lb()

    with patch("xklb.extract.extractor"):
        lb(["extract", "-a"])


def test_lt_args():
    sys.argv = ["listen", "-s", "test"]
    lt()

    sys.argv = ["lt", "-p", "a"]
    lt()


def test_wt_args():
    sys.argv = ["wt", "-s", "test"]
    wt()


def test_multiple_search():
    sys.argv = ["wt", "-s", "test,test1 test2", "test3", "-E", "test4", "-s", "test5"]
    wt()
