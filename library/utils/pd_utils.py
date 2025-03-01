import re
from contextlib import suppress

from library.utils.log_utils import log


def kebab_camel_snake(col):
    col = re.sub(r"(?<!^)(?=[A-Z])", "_", col)
    col = col.lower()
    col = re.sub(r"\s+", "_", col)
    col = re.sub(r"[\]\[\)\(\{\}]+", "", col)
    col = re.sub(r"[\:\-\.]+", "_", col)
    col = re.sub(r"__+", "_", col)
    return col


def columns_snake_case(df):
    df.columns = [kebab_camel_snake(x) if isinstance(x, str) else x for x in df.columns]
    return df


def convert_dtypes(df, clean=False):
    for col in df.columns:
        with suppress(Exception):
            if clean:
                df[col] = df[col].str.replace(r"\[.*|\(.*|\/.*", "", regex=True)
            df.loc[:, col] = df[col].str.replace(",", "").astype(float)

    df = df.convert_dtypes()
    return df


def rename_duplicate_columns(df):
    import pandas

    cols = pandas.Series(df.columns)
    for dup in cols[cols.duplicated()].unique():
        cols[cols[cols == dup].index.values.tolist()] = [
            dup + "_" + str(i) if i != 0 else dup for i in range(sum(cols == dup))
        ]
    df.columns = cols

    return df


def available_name(df, column_name):
    while column_name in df.columns:
        if "_" in column_name:
            base_name, suffix = column_name.rsplit("_", 1)
            column_name = f"{base_name}_{int(suffix) + 1}"
        else:
            column_name = f"{column_name}_1"
    return column_name


def rank_dataframe(original_df, column_weights=None):
    """
    ranked_df = rank_dataframe(
        df,
        column_weights={
            "progress": {"direction": "desc", "weight": 6},
            "size": {"direction": "asc", "weight": 3}
        }
    )
    """
    import pandas as pd

    df = original_df.copy()

    if not column_weights:
        column_weights = {k: {} for k in df.select_dtypes(include=["number"]).columns}

    ranks = pd.DataFrame()
    for col, config in column_weights.items():
        direction = config.get("direction") or "asc"
        weight = config.get("weight") or 1
        method = config.get("method") or "min"
        quantize_method = config.get("quantize_method") or "qcut"
        partition_by = config.get("partition_by")
        na_option = config.get("na_option") or "bottom"
        bins = config.get("bins", 14)  # ~7% q

        ascending = direction == "asc"

        if bins and quantize_method:
            if quantize_method == "cut":
                df[col] = pd.cut(df[col], bins=bins, labels=False, duplicates="drop", include_lowest=True)
            else:
                df[col] = pd.qcut(df[col], q=bins, labels=False, duplicates="drop")

        if partition_by is not None:
            # group by the partition and rank within each group
            s = df.groupby(partition_by)[col]
        else:
            s = df[col]

        rank_col = s.rank(
            method=method,
            na_option=na_option,
            ascending=ascending,
        )
        ranks[col] = rank_col * weight

    unranked_columns = set(df.select_dtypes(include=["number"]).columns) - set(ranks.columns)
    if unranked_columns:
        log.debug(
            "Unranked columns:\n"
            + "\n".join([f"""    "{s}": {{ 'direction': 'desc' }}, """ for s in unranked_columns]),
        )

    sorted_df = original_df.iloc[ranks.sum(axis=1).sort_values().index]
    return sorted_df.reset_index(drop=True)


def count_category(df, key_name):
    df[f"{key_name}_count"] = df.groupby(key_name)[key_name].transform("size")
    return df


def from_dict_add_path_rank(df, sorted_media, new_rank_column_name):
    rank_dict = {item["path"]: rank + 1 for rank, item in enumerate(sorted_media)}
    df[new_rank_column_name] = df["path"].map(rank_dict)
    return df
