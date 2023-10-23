import argparse

from xklb import usage
from xklb.utils import arg_utils, consts, file_utils
from xklb.utils.log_utils import log
from xklb.utils.printing import print_df


def parse_args():
    parser = argparse.ArgumentParser(description="Diff two table-like files", usage=usage.incremental_diff)
    parser.add_argument("--mimetype1", "--filetype1")
    parser.add_argument("--encoding1")
    parser.add_argument("--mimetype2", "--filetype2")
    parser.add_argument("--encoding2")
    parser.add_argument("--table1-name", "--table1", "-t1")
    parser.add_argument("--table2-name", "--table2", "-t2")
    parser.add_argument("--table1-index", type=int)
    parser.add_argument("--table2-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--batch-size", "--batch-rows", default=str(consts.DEFAULT_FILE_ROWS_READ_LIMIT))
    parser.add_argument("--join-keys", action=arg_utils.ArgparseList, help="Comma separated join keys")
    parser.add_argument("--sort", "-u")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("path1", help="path to dataset 1")
    parser.add_argument("path2", help="path to dataset 2")
    args = parser.parse_args()

    # TODO: add an option to load from df2 where ids (select ids from df1)

    if args.batch_size.lower() in ("inf", "none", "all"):
        args.batch_size = None
    else:
        args.batch_size = int(args.batch_size)

    return args


def process_chunks(args):
    chunk_start_row = args.start_row
    chunk_end_row = args.batch_size
    while True:
        dfs1 = file_utils.read_file_to_dataframes(
            args.path1,
            table_name=args.table1_name,
            table_index=args.table1_index,
            start_row=chunk_start_row,
            end_row=chunk_end_row,
            order_by=args.sort,
            encoding=args.encoding1,
            mimetype=args.mimetype1,
        )
        dfs2 = file_utils.read_file_to_dataframes(
            args.path2,
            table_name=args.table2_name,
            table_index=args.table2_index,
            start_row=chunk_start_row,
            end_row=chunk_end_row,
            order_by=args.sort,
            encoding=args.encoding2,
            mimetype=args.mimetype2,
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
            df1.drop(columns=df1.columns[df1.isnull().all()], inplace=True)  # inplace to preserve df.name
            df2.drop(columns=df2.columns[df2.isnull().all()], inplace=True)  # inplace to preserve df.name

            if df1.empty and df2.empty:
                empty_dfs.add(df_idx)
                continue
            elif df1.empty:
                log.warning("df1 has no more rows")
            elif df2.empty:
                log.warning("df2 has no more rows")

            df_diff = df1.merge(df2, on=args.join_keys, how="outer", indicator=True)
            df_diff = df_diff[df_diff["_merge"] != "both"]

            if len(df_diff) > 0:
                print(f"## Diff {args.path1}:{df1.name} and {args.path2}:{df2.name}")
                print()
                print_df(df_diff)
                print()
            del df1
            del df2

        if len(empty_dfs) == len(dfs1):
            break

        del dfs1
        del dfs2

        if args.batch_size:
            if chunk_start_row is None:
                chunk_start_row = 0
            chunk_start_row += args.batch_size
            chunk_end_row += args.batch_size
            log.debug(chunk_end_row)
            continue
        else:
            break


def incremental_diff():
    args = parse_args()
    process_chunks(args)


if __name__ == "__main__":
    incremental_diff()
