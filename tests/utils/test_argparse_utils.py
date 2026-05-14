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


def test_argparse_dict_boolean_conversion():
    """Test that ArgparseDict correctly converts string 'True' and 'False' to boolean."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", action=argparse_utils.ArgparseDict)

    # Test True conversion
    args = parser.parse_args(["--config", "key1=True"])
    assert args.config == {"key1": True}
    assert isinstance(args.config["key1"], bool)

    # Test False conversion - this is the bug: bool("False") returns True
    args = parser.parse_args(["--config", "key2=False"])
    assert args.config == {"key2": False}
    assert isinstance(args.config["key2"], bool)

    # Test mixed types
    args = parser.parse_args(["--config", "enabled=True disabled=False count=42"])
    assert args.config == {"enabled": True, "disabled": False, "count": 42}
    assert args.config["enabled"] is True
    assert args.config["disabled"] is False
