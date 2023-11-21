import argparse
from typing import Dict

from xklb import usage
from xklb.utils import file_utils, nums
from xklb.utils.consts import DEFAULT_FILE_ROWS_READ_LIMIT
from xklb.utils.log_utils import log
from xklb.utils.printing import print_df, print_series


def parse_args():
    parser = argparse.ArgumentParser(description="Perform EDA on one or more files", usage=usage.eda)
    parser.add_argument("--groupby", "--group-by", "-g", action="store_true")
    parser.add_argument("--mimetype", "--filetype")
    parser.add_argument("--encoding")
    parser.add_argument("--table-name", "--table", "-t")
    parser.add_argument("--table-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--end-row", "--nrows", "--limit", "-L", default=str(DEFAULT_FILE_ROWS_READ_LIMIT))
    parser.add_argument("--sort", "-u", default="random()")
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


def df_column_values(df, column_name) -> Dict:
    total = len(df)

    null = df[column_name].isnull().sum()
    zero = (df[column_name] == 0).sum()
    empty = (df[column_name] == "").sum()
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


def print_info(args, df):
    import pandas as pd

    if df.shape == (0, 0):
        print(f"Table [{df.name}] empty")
        return

    if args.end_row is None:
        partial_dataset_msg = ""
    elif args.end_row == DEFAULT_FILE_ROWS_READ_LIMIT:
        partial_dataset_msg = f"(limited by default --end-row {args.end_row})"
    else:
        partial_dataset_msg = f"(limited by --end-row {args.end_row})"
    if args.end_row is not None and args.end_row not in df.shape:
        partial_dataset_msg = ""
    print("### Shape")
    print()
    print(df.shape, partial_dataset_msg)
    print()

    print("### Sample of rows")
    if len(df) > 6:
        print_df(pd.concat([df.head(3), df.tail(3)]))
    else:
        print_df(df.head(6))

    print("### Summary statistics")
    print_df(df.describe())

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
        print_df(same_dtypes.set_index("column"))
    if len(diff_dtypes) > 0:
        print("### Pandas columns with 'converted' dtypes")
        diff_dtypes = pd.DataFrame(diff_dtypes, columns=["column", "original_dtype", "converted_dtype"])
        print_df(diff_dtypes.set_index("column"))

    if len(df) > 15:
        numeric_columns = df.select_dtypes("number").columns.to_list()
        if numeric_columns:
            print("### Numerical columns")
            print()
            print("#### Bins")
            print()
            for col in numeric_columns:
                try:
                    bins = pd.cut(df[col], bins=6)
                    print_df(bins.value_counts().sort_index())
                except TypeError:  # putmask: first argument must be an array
                    log.warning("Could not calculate bins for col %s", col)

        categorical_columns = [s for s in df.columns.to_list() if s not in numeric_columns]
        if categorical_columns:
            high_cardinality_cols = set()
            low_cardinality_cols = set()

            print("### Categorical columns")
            print()
            for col in categorical_columns:
                vc = df[col].value_counts()
                vc = vc[vc > (len(df) * 0.005)]
                if len(vc) > 0:
                    low_cardinality_cols.add(col)
                    print(f"#### common values of {col} column")
                    vc = pd.DataFrame({"Count": vc, "Percentage": (vc / len(df)) * 100}).sort_values(
                        by="Count", ascending=False
                    )
                    print_df(vc.head(30))

                    if args.groupby:
                        groups = df.groupby(col).size()
                        groups = groups[groups >= 15]
                        if len(groups) > 0:
                            print(f"#### group by {col}")
                            print_df(df[df[col].isin(groups.index)].groupby(col).describe())

                unique_count = df[col].nunique()
                if unique_count >= (len(df) * 0.2):
                    high_cardinality_cols.add(col)

            med_cardinality_cols = low_cardinality_cols.intersection(high_cardinality_cols)
            low_cardinality_cols = low_cardinality_cols - med_cardinality_cols
            high_cardinality_cols = high_cardinality_cols - med_cardinality_cols

            if high_cardinality_cols:
                print("#### High cardinality (many unique values)")
                print_series(high_cardinality_cols)
            if med_cardinality_cols:
                print("#### Medium cardinality (many unique but also many similar values)")
                print_series(med_cardinality_cols)
            if low_cardinality_cols:
                print("#### Low cardinality (many similar values)")
                print_series(low_cardinality_cols)

    print("### Missing values")
    print()
    nan_col_sums = df.isna().sum()
    print(
        f"{nan_col_sums.sum():,} nulls/NaNs",
        f"({(nan_col_sums.sum() / (df.shape[0] * df.shape[1])):.1%} dataset values missing)",
    )
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

        print("#### Value stats")
        column_report = pd.DataFrame(df_column_values(df, col) for col in df.columns).set_index("column")
        column_report = column_report.sort_values(["empty_string_count", "zero_count", "null_count"])
        print_df(column_report[["values", "null", "zero", "empty_string"]])


def file_eda(args, path):
    dfs = file_utils.read_file_to_dataframes(
        path,
        table_name=args.table_name,
        table_index=args.table_index,
        start_row=args.start_row,
        end_row=args.end_row,
        order_by=args.sort,
        encoding=args.encoding,
        mimetype=args.mimetype,
    )
    if getattr(args, "repl", False):
        breakpoint()

    for df in dfs:
        print(f"## {path}:{df.name}")
        print_info(args, df)


def eda():
    args = parse_args()
    for path in args.paths:
        file_eda(args, path)


if __name__ == "__main__":
    eda()
