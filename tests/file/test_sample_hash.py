import os.path

from library.__main__ import library as lb

paths = [
    "test.gif",
    "test.hdf",
    "test.mp4",
    "test.nc",
    "test.opus",
]


def test_sample_hash(assert_unchanged, capsys):
    def run(p):
        lb(["sample-hash", os.path.join("tests/data", p)])
        return capsys.readouterr().out.strip()

    captured = {p: run(p).split("\t")[0] for p in paths}
    assert_unchanged(captured)


def test_sample_hash_missing_file(capsys):
    lb(["sample-hash", os.path.join("tests/data", "does-not-exist.xyz")])
    out = capsys.readouterr().out
    assert "Error hashing" in out
    assert "does-not-exist.xyz" in out
    assert not out.startswith("None\t")
