from xklb.folders import similar_folders
from xklb.utils.objects import NoneSpace


def test_is_same_size_group():
    args = NoneSpace(sizes_delta=5, counts_delta=5, total_sizes=True)
    m0 = {"exists": 100, "size": 100}
    assert similar_folders.is_same_size_group(args, m0, {"exists": 96, "size": 100})
    assert similar_folders.is_same_size_group(args, m0, {"exists": 100, "size": 96})

    assert not similar_folders.is_same_size_group(args, m0, {"exists": 110, "size": 100})
    assert not similar_folders.is_same_size_group(args, m0, {"exists": 100, "size": 110})


def test_cluster_by_size():
    args = NoneSpace(sizes_delta=5, counts_delta=5, total_sizes=True)
    media = [{"exists": 100, "size": 100}, {"exists": 100, "size": 100}, {"exists": 100, "size": 100}]
    assert similar_folders.cluster_by_size(args, media) == [0, 0, 0]

    media = [
        {"exists": 100, "size": 100},
        {"exists": 104, "size": 100},
        {"exists": 104, "size": 104},
        {"exists": 108, "size": 104},
        {"exists": 108, "size": 108},
        {"exists": 108, "size": 116},
    ]
    assert similar_folders.cluster_by_size(args, media) == [0, 0, 0, 1, 1, 2]
    assert similar_folders.cluster_by_size(args, list(reversed(media))) == [0, 1, 1, 1, 2, 2]

    media = [
        {"exists": 100, "size": 100},
        {"exists": 108, "size": 116},
        {"exists": 104, "size": 100},
        {"exists": 108, "size": 104},
        {"exists": 104, "size": 104},
        {"exists": 108, "size": 108},
    ]
    assert similar_folders.cluster_by_size(args, media) == [0, 1, 0, 2, 0, 2]
