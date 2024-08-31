import os.path

import pytest

from xklb.__main__ import library as lb

paths = ["test.gif", "test.opus"]


def test_sample_compare():
    with pytest.raises(SystemExit):
        lb(["sample-compare"] + [os.path.join("tests/data", p) for p in paths])
