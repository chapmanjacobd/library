import argparse

from library import usage
from library.utils import arggroups, argparse_utils, consts, file_utils, web
from library.utils.argparse_utils import ArgparseList
from library.utils.log_utils import log
from library.utils.printing import print_df


def parse_args():
    parser = argparse_utils.ArgumentParser(description="Diff two table-like files", usage=usage.incremental_diff)
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
    parser.add_argument("--join-keys", action=ArgparseList, help="Comma separated join keys")
    parser.add_argument(
        "--join-tables",
        "--concat",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Concat all detected tables",
    )
    parser.add_argument("--transpose", action="store_true", help="Swap X and Y axis. Move columns to rows.")
    parser.add_argument("--sort", "-u")
    arggroups.debug(parser)

    parser.add_argument("path1", help="path to dataset 1")
    parser.add_argument("path2", help="path to dataset 2")
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

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
            join_tables=args.join_tables,
            transpose=args.transpose,
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
            join_tables=args.join_tables,
            transpose=args.transpose,
        )

        # TODO: https://github.com/ICRAR/ijson

        tables1 = {df.df_name for df in dfs1}
        tables2 = {df.df_name for df in dfs2}
        common_tables = tables1.intersection(tables2)
        dfs1 = sorted(dfs1, key=lambda df: (df.df_name in common_tables, df.df_name), reverse=True)
        dfs2 = sorted(dfs2, key=lambda df: (df.df_name in common_tables, df.df_name), reverse=True)

        empty_dfs = set()
        for df_idx in range(len(dfs1)):
            df1 = dfs1[df_idx].df
            df2 = dfs2[df_idx].df
            df1_name = dfs1[df_idx].df_name
            df2_name = dfs2[df_idx].df_name

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

            df_diff = df1.merge(df2, on=args.join_keys, how="outer", indicator=True)
            df_diff = df_diff[df_diff["_merge"] != "both"]

            if len(df_diff) > 0:
                print(f"## Diff {args.path1}:{df1_name} and {args.path2}:{df2_name}")
                print_df(df_diff)
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
    web.requests_session(args)  # configure session
    process_chunks(args)
