import argparse, sys

from xklb import usage
from xklb.utils import arg_utils, consts, file_utils
from xklb.utils.log_utils import log
from xklb.utils.printing import print_df


def parse_args():
    parser = argparse.ArgumentParser(description="Perform EDA on one or more files", usage=usage.incremental_diff)
    parser.add_argument("--table1-name", "--table1", "-t1")
    parser.add_argument("--table2-name", "--table2", "-t2")
    parser.add_argument("--table1-index", type=int)
    parser.add_argument("--table2-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--end-row", "--nrows", "--limit", "-L", default=str(consts.DEFAULT_FILE_ROWS_READ_LIMIT))
    parser.add_argument("--sort", "-u")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("path1", help="path to dataset 1")
    parser.add_argument("path2", help="path to dataset 2")
    parser.add_argument(
        "--primary-keys", "--pk", "-pk", action=arg_utils.ArgparseList, help="Comma separated primary keys"
    )
    args = parser.parse_args()

    # TODO: add an option to load from df2 where ids (select ids from df1)

    if args.end_row.lower() in ("inf", "none", "all"):
        args.end_row = None
    else:
        args.end_row = int(args.end_row)

    args.batch_size = None
    if args.end_row is not None and args.start_row is not None:
        args.batch_size = abs(args.end_row - args.start_row)

    return args


def process_chunk(args):
    dfs1 = file_utils.read_file_to_dataframes(
        args.path1,
        table_name=args.table1_name,
        table_index=args.table1_index,
        start_row=args.start_row,
        end_row=args.end_row,
        order_by=args.sort,
    )
    dfs2 = file_utils.read_file_to_dataframes(
        args.path2,
        table_name=args.table2_name,
        table_index=args.table2_index,
        start_row=args.start_row,
        end_row=args.end_row,
        order_by=args.sort,
    )

    # TODO: https://github.com/ICRAR/ijson

    tables1 = set(df.name for df in dfs1)
    tables2 = set(df.name for df in dfs2)
    common_tables = tables1.intersection(tables2)
    dfs1 = sorted(dfs1, key=lambda df: (df.name in common_tables, df.name), reverse=True)
    dfs2 = sorted(dfs2, key=lambda df: (df.name in common_tables, df.name), reverse=True)

    empty_dfs = set()
    for df_idx in range(len(dfs1)):
        df1 = dfs1[df_idx]
        df2 = dfs2[df_idx]

        # drop cols with all nulls to allow merging "X" and object columns
        df1 = df1.drop(columns=df1.columns[df1.isnull().all()])
        df2 = df2.drop(columns=df2.columns[df2.isnull().all()])

        if df1.empty and df2.empty:
            empty_dfs.add(df_idx)
            continue
        elif df1.empty:
            log.warning("df1 has no more rows")
        elif df2.empty:
            log.warning("df2 has no more rows")

        df_diff = df1.merge(df2, on=args.primary_keys, how="outer", indicator=True)
        df_diff = df_diff[df_diff["_merge"] != "both"]

        if len(df_diff) > 0:
            print(f"## Diff {args.path1}:{df1.name} and {args.path2}:{df2.name}")
            print()
            print_df(df_diff)
            print()
        del df1
        del df2

    if len(empty_dfs) == len(dfs1):
        return

    del dfs1
    del dfs2

    if args.batch_size:
        args.start_row = args.batch_size + (args.start_row or 0)
        args.end_row += args.batch_size
        print(args.end_row)

        return process_chunk(args)


def incremental_diff():
    args = parse_args()
    if args.batch_size:
        sys.setrecursionlimit(10_000)
    process_chunk(args)


if __name__ == "__main__":
    incremental_diff()
