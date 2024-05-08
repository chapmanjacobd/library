from xklb.files import similar_files
from xklb.folders import similar_folders
from xklb.utils.objects import NoneSpace

args = NoneSpace(sizes_delta=5, counts_delta=5, durations_delta=5, total_sizes=True, total_durations=True)


def test_is_same_group():
    m0 = {"exists": 100, "size": 100, "duration": 5}
    assert similar_folders.is_same_group(args, m0, {"exists": 96, "size": 100, "duration": 5})
    assert similar_folders.is_same_group(args, m0, {"exists": 100, "size": 96, "duration": 5})

    assert not similar_folders.is_same_group(args, m0, {"exists": 110, "size": 100, "duration": 5})
    assert not similar_folders.is_same_group(args, m0, {"exists": 100, "size": 110, "duration": 5})

    assert not similar_folders.is_same_group(args, m0, {"exists": 96, "size": 100, "duration": 10})
    assert not similar_folders.is_same_group(args, m0, {"exists": 100, "size": 96, "duration": 10})


def test_cluster_by_size():
    media = [{"duration": 100, "size": 100}, {"duration": 100, "size": 100}, {"duration": 100, "size": 100}]
    assert similar_files.cluster_by_size(args, media) == [0, 0, 0]

    media = [
        {"duration": 100, "size": 100},
        {"duration": 104, "size": 100},
        {"duration": 104, "size": 104},
        {"duration": 108, "size": 104},
        {"duration": 108, "size": 108},
        {"duration": 108, "size": 116},
    ]
    assert similar_files.cluster_by_size(args, media) == [0, 0, 0, 1, 1, 2]
    assert similar_files.cluster_by_size(args, list(reversed(media))) == [0, 1, 1, 1, 2, 2]

    media = [
        {"duration": 100, "size": 100},
        {"duration": 108, "size": 116},
        {"duration": 104, "size": 100},
        {"duration": 108, "size": 104},
        {"duration": 104, "size": 104},
        {"duration": 108, "size": 108},
    ]
    assert similar_files.cluster_by_size(args, media) == [0, 1, 0, 2, 0, 2]
