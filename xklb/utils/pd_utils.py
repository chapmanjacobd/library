import re


def kebab_camel_snake(col):
    col = re.sub(r"(?<!^)(?=[A-Z])", "_", col)
    col = col.lower()
    col = re.sub(r"[-:.]", "_", col)
    col = re.sub(r"\s+", "_", col)
    col = re.sub(r"_+", "_", col)
    return col


def columns_snake_case(df):
    df.columns = [kebab_camel_snake(x) for x in df.columns]
    return df
