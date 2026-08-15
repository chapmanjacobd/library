import os.path

import pytest

from library.__main__ import library as lb

paths = ["test.gif", "test.opus"]


def test_sample_compare():
    with pytest.raises(SystemExit):
        lb(["sample-compare"] + [os.path.join("tests/data", p) for p in paths])


def test_sample_cmp_missing_file():
    # 4.1: missing files are silently suppressed, so a nonexistent path makes
    # sample_cmp return True (exit 0) which is dangerous in dedupe workflows.
    import tempfile

    from library.files import sample_compare

    f1 = tempfile.mktemp()
    f2 = tempfile.mktemp()
    missing = tempfile.mktemp()
    with open(f1, "w") as f:
        f.write("hello world")
    with open(f2, "w") as f:
        f.write("hello world")

    try:
        assert sample_compare.sample_cmp(f1, f2, missing) is False
    finally:
        for p in (f1, f2):
            import os

            if os.path.exists(p):
                os.unlink(p)
