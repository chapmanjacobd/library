from types import SimpleNamespace

from library.file.similar_files import cluster_by_content, cluster_by_size, content_similarity, sample_positions


def test_cluster_by_size_groups_within_size_delta():
    args = SimpleNamespace(
        filter_sizes=True,
        filter_durations=False,
        sizes_delta=10.0,
        durations_delta=10.0,
    )
    media = [{"size": 100}, {"size": 105}, {"size": 200}]

    assert cluster_by_size(args, media) == [0, 0, 1]


def test_sample_positions_are_deterministic():
    assert sample_positions(100, 10, 4) == [0, 30, 60, 90]
    assert sample_positions(5, 10, 4) == [0]


def test_content_similarity_is_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"abcdefghij" * 10)
    second.write_bytes(b"abcdefghij" * 10)

    assert content_similarity(first, second, chunk_size=3, sample_count=5) == 1
    assert content_similarity(first, first, chunk_size=3, sample_count=5) == 1


def test_cluster_by_content_groups_matching_samples(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    different = tmp_path / "different"
    first.write_bytes(b"abcdefghij" * 10)
    second.write_bytes(b"abcdefghij" * 10)
    different.write_bytes(b"0123456789" * 10)
    args = SimpleNamespace(content_chunk_size=3, content_samples=5, content_threshold=1)
    media = [{"path": str(first)}, {"path": str(second)}, {"path": str(different)}]

    assert cluster_by_content(args, media) == [0, 0, 1]
