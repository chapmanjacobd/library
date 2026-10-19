from types import SimpleNamespace

from library.file.similar_files import cluster_by_size


def test_cluster_by_size_groups_within_size_delta():
    args = SimpleNamespace(
        filter_sizes=True,
        filter_durations=False,
        sizes_delta=10.0,
        durations_delta=10.0,
    )
    media = [{"size": 100}, {"size": 105}, {"size": 200}]

    assert cluster_by_size(args, media) == [0, 0, 1]
