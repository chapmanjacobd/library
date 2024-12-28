import re
from contextlib import suppress


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


def rank_dataframe(df, column_weights):
    """
    ranked_df = rank_dataframe(
        df,
        column_weights={
            "progress": {"direction": "desc", "weight": 6},
            "size": {"direction": "asc", "weight": 3}
        }
    )
    """
    ranks = df[column_weights.keys()].apply(
        lambda x: x.rank(
            method="min",
            na_option="bottom",
            ascending=column_weights.get(x.name, {}).get("direction") == "asc",
        )
        * column_weights.get(x.name, {}).get("weight", 1),
    )

    unranked_columns = set(df.select_dtypes(include=["number"]).columns) - set(ranks.columns)
    if unranked_columns:
        print(
            "Unranked columns:\n"
            + "\n".join([f"""    "{s}": {{ 'direction': 'desc' }}, """ for s in unranked_columns]),
        )

    scaled_ranks = (ranks - 1) / (len(ranks.columns) - 1)
    scaled_df = df.iloc[scaled_ranks.sum(axis=1).sort_values().index]
    return scaled_df.reset_index(drop=True)


def count_category(df, key_name):
    df[f"{key_name}_count"] = df.groupby(key_name)[key_name].transform("size")
    return df


def from_dict_add_path_rank(df, sorted_media, new_rank_column_name):
    rank_dict = {item["path"]: rank + 1 for rank, item in enumerate(sorted_media)}
    df[new_rank_column_name] = df["path"].map(rank_dict)
    return df
