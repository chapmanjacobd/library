from library.utils import consts, file_utils


def test_filter_deleted(tmp_path):
    # Create some files
    f1 = tmp_path / "f1.txt"
    f1.touch()
    f2 = tmp_path / "f2.txt"
    # f2 does not exist

    paths = [str(f1), str(f2)]
    filtered = file_utils.filter_deleted(paths)

    assert str(f1) in filtered
    assert str(f2) not in filtered
    assert len(filtered) == 1


def test_get_file_stats(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")

    d = {"path": str(f)}
    result = file_utils.get_file_stats(d)

    assert result["size"] == 5
    assert result["time_created"] > 0
    assert result["time_modified"] > 0
    assert result["time_deleted"] == 0


def test_get_file_stats_missing(tmp_path):
    f = tmp_path / "missing.txt"
    d = {"path": str(f)}

    result = file_utils.get_file_stats(d)

    assert result["size"] is None
    assert result["time_deleted"] == consts.APPLICATION_START


def test_detect_mimetype(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    assert file_utils.detect_mimetype(str(f)) == "text/plain"

    f2 = tmp_path / "test.json"
    f2.write_text("{}")
    # detect_mimetype might return application/json or text/plain depending on strictness,
    # but puremagic/mimetypes should handle json. puremagic usually returns capitalized name if matched by magic
    mimetype = file_utils.detect_mimetype(str(f2))
    assert mimetype in ("application/json", "JSON")


def test_read_file_to_dataframes_json(tmp_path):
    f = tmp_path / "test.json"
    f.write_text('[{"col1": 1, "col2": "a"}, {"col1": 2, "col2": "b"}]')

    dfs = file_utils.read_file_to_dataframes(str(f))

    assert len(dfs) == 1
    df = dfs[0].df
    assert len(df) == 2
    assert df.iloc[0]["col1"] == 1
    assert df.iloc[1]["col2"] == "b"


def test_read_file_to_dataframes_csv(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("col1,col2\n1,a\n2,b")

    dfs = file_utils.read_file_to_dataframes(str(f))

    assert len(dfs) == 1
    df = dfs[0].df
    assert len(df) == 2
    assert df.iloc[0]["col1"] == 1
    assert df.iloc[1]["col2"] == "b"
