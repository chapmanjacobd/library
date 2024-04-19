import re


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
        try:
            if clean:
                df[col] = df[col].str.replace(r"\[.*|\(.*|\/.*", "", regex=True)
            df.loc[:, col] = df[col].str.replace(",", "").astype(float)
        except Exception:
            continue  # column was not numeric after all (•́⍜•̀), skip
    df = df.convert_dtypes()
    return df
