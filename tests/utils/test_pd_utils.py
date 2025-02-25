import pandas as pd
import pytest

from library.utils import pd_utils


def test_no_duplicates():
    data = {"A": [1, 2, 3], "B": [4, 5, 6], "C": [7, 8, 9]}
    df = pd.DataFrame(data)
    result = pd_utils.rename_duplicate_columns(df)
    assert list(result.columns) == ["A", "B", "C"]


def test_one_duplicate():
    df1 = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
    df2 = pd.DataFrame({"A": [7, 8, 9]})
    df = pd.concat([df1, df2], axis=1)
    result = pd_utils.rename_duplicate_columns(df)
    assert list(result.columns) == ["A", "B", "A_1"]


def test_multiple_duplicates():
    df1 = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
    df2 = pd.DataFrame({"A": [7, 8, 9], "B": [13, 14, 15]})
    df = pd.concat([df1, df2], axis=1)
    result = pd_utils.rename_duplicate_columns(df)
    assert list(result.columns) == ["A", "B", "A_1", "B_1"]


def test_multiple_occurrences():
    df1 = pd.DataFrame({"A": [1, 2, 3]})
    df2 = pd.DataFrame({"A": [4, 5, 6]})
    df3 = pd.DataFrame({"A": [7, 8, 9]})
    df = pd.concat([df1, df2, df3], axis=1)
    result = pd_utils.rename_duplicate_columns(df)
    assert list(result.columns) == ["A", "A_1", "A_2"]


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "item": ["A", "B", "C", "D", "E"],
            "progress": [1, 4, 6, 12, 16],
            "size": [15, 4, 3, 2, 1],
            "category": ["X", "Y", "X", "Y", "X"],
            "category2": ["2023-01-01", "2023-01-01", "2023-01-02", "2023-01-02", "2023-01-02"],
        }
    )


@pytest.fixture
def unsorted_df():
    return pd.DataFrame(
        {
            "item": ["A", "B", "C", "D", "E"],
            "progress": [6, 12, 16, 1, 4],
            "size": [15, 1, 4, 3, 2],
        }
    )


@pytest.fixture
def many_df():
    return pd.DataFrame(
        {
            "item": ["A", "B", "C", "D", "E"],
            "progress": [1, 2, 3, 4, 5],
            "size": [5000, None, 3000, None, 1000],
        }
    )


@pytest.fixture
def weight_df():
    return pd.DataFrame(
        {
            "item": ["A", "B", "C", "D", "E"],
            "progress": [1, 2, 3, 4, 5],
            "progress2": [2, 4, 6, 8, 10],
            "size": [5, 4, 3, 2, 1],
            "size2": [10, 8, 6, 4, 2],
        }
    )


@pytest.fixture
def sample_column_weights_normal():
    return {
        "progress": {"direction": "desc", "weight": 2},
        "size": {"direction": "asc", "weight": 1},
    }


def test_no_ranking(sample_df):
    default_df = pd_utils.rank_dataframe(sample_df.copy(), {})
    ranked_df = pd_utils.rank_dataframe(
        sample_df.copy(),
        {
            "progress": {"direction": "asc"},
            "size": {"direction": "asc"},
        },
    )
    pd.testing.assert_frame_equal(ranked_df, default_df)

    expected_order = ["A", "B", "C", "D", "E"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()

    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_no_ranking2(sample_df):
    column_weights = {
        "progress": {"direction": "desc"},
        "size": {"direction": "desc"},
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["A", "B", "C", "D", "E"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()

    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_normal_ranking(sample_df, sample_column_weights_normal):
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), sample_column_weights_normal)

    expected_order = ["E", "D", "C", "B", "A"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()

    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_ascending(sample_df):
    column_weights = {
        "progress": {"direction": "asc"},
        "size": {"direction": "asc"},
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["A", "B", "C", "D", "E"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()

    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_ascending2(sample_df):
    column_weights = {
        "progress": {"direction": "asc"},
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["A", "B", "C", "D", "E"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()

    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_ascending3(sample_df):
    column_weights = {
        "size": {"direction": "desc"},
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["A", "B", "C", "D", "E"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()

    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_descending(sample_df):
    column_weights = {
        "progress": {"direction": "desc"},
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["E", "D", "C", "B", "A"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()

    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_descending2(sample_df):
    column_weights = {
        "size": {"direction": "asc"},
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["E", "D", "C", "B", "A"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()

    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_different_weights(unsorted_df):
    column_weights = {
        "progress": {"weight": 5},
        "size": {"weight": 1},
    }
    ranked_df = pd_utils.rank_dataframe(unsorted_df.copy(), column_weights)

    expected_order = ["D", "E", "A", "B", "C"]
    expected_df = unsorted_df.set_index("item").loc[expected_order].reset_index()
    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_different_weights2(unsorted_df):
    ranked_df = pd_utils.rank_dataframe(unsorted_df.copy())

    expected_order = ["D", "E", "B", "A", "C"]
    expected_df = unsorted_df.set_index("item").loc[expected_order].reset_index()
    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_different_weights3(weight_df):
    ranked_df = pd_utils.rank_dataframe(
        weight_df.copy(),
        {
            "size": {"weight": 2},
            "progress2": {"weight": 1},
        },
    )

    expected_order = ["E", "D", "C", "B", "A"]
    expected_df = weight_df.set_index("item").loc[expected_order].reset_index()
    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_nulls(many_df):
    ranked_df = pd_utils.rank_dataframe(
        many_df.copy(),
        {
            "progress": {"direction": "desc"},
            "size": {"direction": "desc"},
        },
    )

    expected_order = ["E", "C", "D", "A", "B"]
    expected_df = many_df.set_index("item").loc[expected_order].reset_index()
    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_nulls2(many_df):
    ranked_df = pd_utils.rank_dataframe(many_df.copy())

    expected_order = ["A", "C", "B", "E", "D"]
    expected_df = many_df.set_index("item").loc[expected_order].reset_index()
    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_partitioned_ranking_single_column(sample_df):
    column_weights = {
        "size": {"direction": "asc", "partition_by": "category"},
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["D", "E", "C", "B", "A"]  # 'size' ranked within each 'category'
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()
    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_partitioned_ranking_single_column2(sample_df):
    column_weights = {
        "size": {"direction": "asc", "partition_by": "category2"},
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["B", "E", "D", "A", "C"]  # 'size' ranked within each 'category2'
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()
    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_partitioned_ranking_multi_column(sample_df):
    column_weights = {
        "progress": {
            "direction": "desc",
            "partition_by": ["category", "category2"],
        },
    }
    ranked_df = pd_utils.rank_dataframe(sample_df.copy(), column_weights)

    expected_order = ["A", "B", "D", "E", "C"]
    expected_df = sample_df.set_index("item").loc[expected_order].reset_index()
    pd.testing.assert_frame_equal(ranked_df, expected_df)


def test_rank_column_not_found(sample_df):
    with pytest.raises(KeyError):
        pd_utils.rank_dataframe(sample_df.copy(), {"non_existent_column": {}})


def test_partition_column_not_found(sample_df, sample_column_weights_normal):
    column_weights_with_bad_partition = sample_column_weights_normal.copy()
    column_weights_with_bad_partition["size"]["partition_by"] = "non_existent_column"

    with pytest.raises(KeyError):
        pd_utils.rank_dataframe(sample_df.copy(), column_weights_with_bad_partition)


def test_rank_dataframe_qcut():
    df = pd.DataFrame({"value": [5, 12, 8, 25, 15, 2, 9]})
    ranked_df = pd_utils.rank_dataframe(df, column_weights={"value": {"bins": 4}})
    expected = [5, 2, 9, 8, 12, 25, 15]
    assert list(ranked_df["value"].values) == expected


def test_rank_dataframe_cut():
    df = pd.DataFrame({"value": [5, 12, 8, 25, 15, 2, 9]})
    ranked_df = pd_utils.rank_dataframe(df, column_weights={"value": {"quantize_method": "cut", "bins": 4}})
    expected = [5, 2, 8, 12, 9, 15, 25]
    assert list(ranked_df["value"].values) == expected


def test_rank_dataframe_cut_list():
    df = pd.DataFrame({"value": [5, 12, 8, 25, 15, 2, 9]})
    ranked_df = pd_utils.rank_dataframe(
        df, column_weights={"value": {"quantize_method": "cut", "bins": [0, 10, 20, 30]}}
    )
    expected = [5, 8, 9, 2, 15, 12, 25]
    assert list(ranked_df["value"].values) == expected
