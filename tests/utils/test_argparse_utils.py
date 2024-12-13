import argparse

import pytest

from library.utils import argparse_utils


def test_argparse_slice():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slice", action=argparse_utils.ArgparseSlice)

    args = parser.parse_args(["--slice", "1:5:2"])
    assert args.slice == slice(1, 5, 2)

    args = parser.parse_args(["--slice", "3"])
    assert args.slice == slice(3, None)

    args = parser.parse_args(["--slice", "3:4"])
    assert args.slice == slice(3, 4)

    args = parser.parse_args(["--slice", ":4"])
    assert args.slice == slice(None, 4)

    with pytest.raises(ValueError):
        parser.parse_args(["--slice", "1:2:3:4"])
    with pytest.raises(ValueError):
        parser.parse_args(["--slice", ""])
    with pytest.raises((argparse.ArgumentError, SystemExit)):
        parser.parse_args(["--slice"])
