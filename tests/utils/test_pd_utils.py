import pandas as pd

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
