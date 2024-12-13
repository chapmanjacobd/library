from library.folders import scatter
from tests import utils


def test_rebin_folders():
    def dummy_folders(num_paths, base="/tmp/"):
        return [f"{base}{x}" for x in range(1, num_paths + 1)]

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5), 2)
    assert untouched == []
    expected = ["/tmp/1/1", "/tmp/1/2", "/tmp/2/3", "/tmp/2/4", "/tmp/3/5"]
    assert list(t[1] for t in rebinned) == [utils.p(s) for s in expected]

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5), 4)
    expected = ["/tmp/1/1", "/tmp/1/2", "/tmp/1/3", "/tmp/1/4", "/tmp/2/5"]
    assert list(t[1] for t in rebinned) == [utils.p(s) for s in expected]
    assert untouched == []

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5) + dummy_folders(5, "/tmp/f/"), 4)
    expected = [
        "/tmp/1/1",
        "/tmp/1/2",
        "/tmp/1/3",
        "/tmp/1/4",
        "/tmp/2/5",
        "/tmp/f/1/1",
        "/tmp/f/1/2",
        "/tmp/f/1/3",
        "/tmp/f/1/4",
        "/tmp/f/2/5",
    ]
    assert list(t[1] for t in rebinned) == [utils.p(s) for s in expected]
    assert untouched == []

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5) + dummy_folders(5, "/tmp/f/"), 5)
    assert rebinned == []
    assert len(untouched) == 10

    untouched, rebinned = scatter.rebin_folders(dummy_folders(5) + dummy_folders(5, "/tmp/f/"), 6)
    assert rebinned == []
    assert len(untouched) == 10
