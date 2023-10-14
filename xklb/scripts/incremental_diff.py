import argparse

from xklb import usage
from xklb.utils import arg_utils, file_utils
from xklb.utils.consts import DEFAULT_FILE_ROWS_READ_LIMIT
from xklb.utils.printing import print_df


def parse_args():
    parser = argparse.ArgumentParser(description="Perform EDA on one or more files", usage=usage.incremental_diff)
    parser.add_argument("--table1-name", "--table1", "-t1")
    parser.add_argument("--table2-name", "--table2", "-t2")
    parser.add_argument("--table1-index", type=int)
    parser.add_argument("--table2-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--end-row", "--nrows", "--limit", "-L", default=str(DEFAULT_FILE_ROWS_READ_LIMIT))
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("path1", help="path to dataset 1")
    parser.add_argument("path2", help="path to dataset 2")
    parser.add_argument(
        "--primary-keys", "--pk", "-pk", action=arg_utils.ArgparseList, help="Comma separated primary keys"
    )
    args = parser.parse_args()

    if args.end_row.lower() in ("inf", "none", "all"):
        args.end_row = None
    else:
        args.end_row = int(args.end_row)

    args.batch_size = args.end_row
    if args.batch_size is not None and args.start_row is not None:
        args.batch_size -= args.start_row

    return args


def process_chunk(args):
    dfs1 = file_utils.read_file_to_dataframes(
        args.path1,
        table_name=args.table1_name,
        table_index=args.table1_index,
        start_row=args.start_row,
        end_row=args.end_row,
    )
    dfs2 = file_utils.read_file_to_dataframes(
        args.path2,
        table_name=args.table2_name,
        table_index=args.table2_index,
        start_row=args.start_row,
        end_row=args.end_row,
    )

    # TODO: https://github.com/ICRAR/ijson

    tables1 = set(df.name for df in dfs1)
    tables2 = set(df.name for df in dfs2)
    common_tables = tables1.intersection(tables2)
    dfs1 = sorted(dfs1, key=lambda df: (df.name in common_tables, df.name), reverse=True)
    dfs2 = sorted(dfs2, key=lambda df: (df.name in common_tables, df.name), reverse=True)

    for df_idx in range(len(dfs1)):
        df1 = dfs1[df_idx]
        df2 = dfs2[df_idx]

        print(f"# Diff {args.path1}:{df1.name} and {args.path2}:{df2.name}")
        print()

        df_diff = df1.merge(df2, on=args.primary_keys, how="outer", indicator=True)
        df_diff = df_diff[df_diff["_merge"] != "both"]
        print_df(df_diff)

    if args.batch_size:
        args.start_row += args.batch_size
        args.end_row += args.batch_size

        process_chunk(args)


def incremental_diff():
    args = parse_args()
    process_chunk(args)


if __name__ == "__main__":
    incremental_diff()
