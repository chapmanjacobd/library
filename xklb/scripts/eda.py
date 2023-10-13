#!/usr/bin/python

import argparse
from typing import Dict

from xklb import usage
from xklb.utils import file_utils, nums
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser(description="Perform EDA on one or more files", usage=usage.eda)
    parser.add_argument("--table", "-t")
    parser.add_argument("--table-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--end-row", "--nrows", "--limit", "-L", default="20000")
    parser.add_argument("--repl", "-r", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument(
        "paths",
        metavar="path",
        nargs="+",
        help="path to one or more files",
    )
    args = parser.parse_args()

    if args.end_row.lower() in ("inf", "none", "all"):
        args.end_row = None
    else:
        args.end_row = int(args.end_row)

    return args


def pd_read_sqlite(args, path):
    import pandas as pd
    from sqlite_utils import Database

    db = Database(path)

    if args.table:
        tables = [args.table]
    else:
        tables = [
            s
            for s in db.table_names() + db.view_names()
            if not any(["_fts_" in s, s.endswith("_fts"), s.startswith("sqlite_")])
        ]
        if args.table_index:
            tables = [args.table_index]

    dfs = []
    for table in tables:
        df = pd.DataFrame(db[table].rows_where(offset=args.start_row, limit=args.end_row, order_by="random()"))
        df.name = table
        dfs.append(df)

    return dfs


def read_file_to_dataframes(args, path):
    import pandas as pd

    skiprows = args.start_row
    nrows = args.end_row

    mimetype = file_utils.mimetype(path)
    log.info(mimetype)

    if mimetype in ("text/csv",):
        dfs = [pd.read_csv(path, nrows=nrows, skiprows=skiprows or 0)]
    elif mimetype in ("text/tab-separated-values",):
        dfs = [pd.read_csv(path, delimiter="\t", nrows=nrows, skiprows=skiprows or 0)]
    elif mimetype in (
        "application/vnd.ms-excel",
        "Excel spreadsheet subheader",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        excel_data = pd.read_excel(path, sheet_name=args.table or args.table_index, nrows=nrows, skiprows=skiprows)
        dfs = []
        if isinstance(excel_data, pd.DataFrame):
            worksheet_names = excel_data.index.levels[0]
            for name in worksheet_names:
                df = excel_data.loc[name]
                df.name = name
                dfs.append(df)
        else:
            for worksheet_name, df in excel_data.items():
                df.name = worksheet_name
                dfs.append(df)
    elif mimetype in ("application/json",):
        dfs = [pd.read_json(path)]
    elif mimetype in ("JSON Lines", "GeoJSON Lines"):
        dfs = [pd.read_json(path, nrows=nrows, lines=True)]
    elif mimetype in ("application/parquet",):
        dfs = [pd.read_parquet(path)]
    elif mimetype in ("Pickle", "application/octet-stream"):
        dfs = [pd.read_pickle(path)]
    elif mimetype in ("text/html",):
        dfs = pd.read_html(path, skiprows=skiprows)
    elif mimetype in ("SQLite database file",):
        dfs = pd_read_sqlite(args, path)
    elif mimetype in ("Stata",):
        dfs = [pd.read_stata(path)]
    elif mimetype in ("Feather",):
        dfs = [pd.read_feather(path)]
    elif mimetype in ("application/x-hdf",):
        dfs = [pd.read_hdf(path, start=skiprows, stop=nrows)]
    elif mimetype in ("ORC",):
        dfs = [pd.read_orc(path)]
    elif mimetype in ("Parquet",):
        dfs = [pd.read_parquet(path)]
    elif mimetype in ("text/xml",):
        dfs = [pd.read_xml(path)]
    elif mimetype in ("application/x-netcdf",):
        import xarray as xr

        ds = xr.open_dataset(path)
        dfs = [ds.to_dataframe()]
    elif mimetype in ("Zarr",):
        import xarray as xr

        ds = xr.open_zarr(path)
        dfs = [ds.to_dataframe()]
    else:
        raise ValueError(f"{path}: Unsupported file type: {mimetype}")

    for table_index, df in enumerate(dfs):
        if not hasattr(df, "name"):
            df.name = str(table_index)

    return dfs


def print_md(df):
    print(df.to_markdown(tablefmt="github"))


def print_series(s):
    if len(s) > 0:
        print()
        print("\n".join([f"- {col}" for col in s]))
        print()


def df_column_values(dataframe, column_name) -> Dict:
    total = len(dataframe)

    null = dataframe[column_name].isnull().sum()
    zero = (dataframe[column_name] == 0).sum()
    empty = (dataframe[column_name] == "").sum()
    values = total - empty - zero - null

    return {
        "values_count": values,
        "null_count": null,
        "zero_count": zero,
        "empty_string_count": empty,
        "column": column_name,
        "null": f"{null} ({nums.percent(null, total):.1f}%)",
        "zero": f"{zero} ({nums.percent(zero, total):.1f}%)",
        "empty_string": f"{empty} ({nums.percent(empty, total):.1f}%)",
        "values": f"{values} ({nums.percent(values, total):.1f}%)",
    }


def print_info(df):
    import pandas as pd

    if df.shape == (0, 0):
        print(f"Table [{df.name}] empty")
        return

    print("### Shape")
    print(df.shape)
    print()

    print("### Sample of rows")
    print_md(df.head())
    print()
    print("### Summary statistics")
    print_md(df.describe())
    print()

    converted = df.convert_dtypes()
    same_dtypes = []
    diff_dtypes = []
    for col in df.columns:
        if df.dtypes[col] == converted.dtypes[col]:
            same_dtypes.append((col, df.dtypes[col]))
        else:
            diff_dtypes.append((col, df.dtypes[col], converted.dtypes[col]))
    if len(same_dtypes) > 0:
        print("### Pandas columns with 'original' dtypes")
        same_dtypes = pd.DataFrame(same_dtypes, columns=["column", "dtype"])
        print_md(same_dtypes.set_index("column"))
        print()
    if len(diff_dtypes) > 0:
        print("### Pandas columns with 'converted' dtypes")
        diff_dtypes = pd.DataFrame(diff_dtypes, columns=["column", "original_dtype", "converted_dtype"])
        print_md(diff_dtypes.set_index("column"))
        print()

    print("### Missing values")
    nan_col_sums = df.isna().sum()
    print(f"{nan_col_sums.sum():,} NaNs", f"({(nan_col_sums.sum() / (df.shape[0] * df.shape[1])):.1%})")
    print()

    if nan_col_sums.sum():
        no_nas = df.columns[df.notnull().all()]
        if len(no_nas) > 0:
            print(f"#### {len(no_nas)} columns with no missing values")
            print_series(no_nas)

        all_nas = df.columns[df.isnull().all()]
        if len(all_nas) > 0:
            print(f"#### {len(all_nas)} columns with all missing values")
            print_series(all_nas)

        print(f"#### Value stats")
        column_report = pd.DataFrame(df_column_values(df, col) for col in df.columns).set_index("column")
        column_report = column_report.sort_values(["empty_string_count", "zero_count", "null_count"])
        print_md(column_report[["values", "null", "zero", "empty_string"]])
        print()


def eda():
    args = parse_args()
    for path in args.paths:
        dfs = read_file_to_dataframes(args, path)
        if args.repl:
            breakpoint()

        for df in dfs:
            print(f"## {path}:{df.name}")
            print_info(df)


if __name__ == "__main__":
    eda()
