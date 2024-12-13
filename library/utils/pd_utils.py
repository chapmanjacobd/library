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
