from library.filesystem import modified_hist


def test_find_files_uses_library_stat_fields(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("content")

    records = modified_hist.find_files(str(tmp_path))

    assert records == [(int(path.stat().st_mtime), str(path))]


def test_histogram_buckets_are_deterministic():
    records = [(0, "a"), (1, "b"), (2, "c"), (10, "d")]

    labels, buckets = modified_hist.histogram_buckets(records, intervals=2)

    assert labels == [0, 10]
    assert buckets == [3, 1]


def test_outlier_records_use_iqr_fences():
    records = [(0, "a"), (1, "b"), (2, "c"), (100, "outlier")]

    assert modified_hist.outlier_records(records) == [(100, "outlier")]
