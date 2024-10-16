from pathlib import Path

from xklb import usage
from xklb.utils import arggroups, argparse_utils, file_utils, pd_utils, web
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.tables_add)
    arggroups.table_like(parser)
    parser.set_defaults(end_row="inf")
    parser.add_argument("--sort", "-u", default="random()")

    parser.add_argument(
        "--primary-keys", "--pk", action=argparse_utils.ArgparseList, help="Comma separated primary keys"
    )
    parser.add_argument(
        "--business-keys", "--bk", action=argparse_utils.ArgparseList, help="Comma separated business keys"
    )

    parser.add_argument("--upsert", action="store_true")
    parser.add_argument("--ignore", "--only-new-rows", action="store_true")

    parser.add_argument("--only-target-columns", action="store_true")
    parser.add_argument("--skip-columns", action=argparse_utils.ArgparseList)
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=True)

    arggroups.table_like_post(args)

    return args


def table_add(args, path):
    dfs = file_utils.read_file_to_dataframes(
        path,
        table_name=args.table_name,
        table_index=args.table_index,
        start_row=args.start_row,
        end_row=args.end_row,
        order_by=args.sort,
        encoding=args.encoding,
        mimetype=args.mimetype,
        join_tables=args.join_tables,
        transpose=args.transpose,
        skip_headers=args.skip_headers,
    )
    for i, (df_name, df) in enumerate(dfs):
        if args.table_rename:
            table = args.table_rename.replace("%n", df_name).replace("%i", str(i))
        elif args.table_name == "stdin":
            table = "stdin"
        elif df_name.isnumeric():
            table = Path(path).stem
            if len(dfs) > 1:
                table += df_name
        else:
            table = df_name
        log.info("[%s]: %s", path, table)

        df = pd_utils.rename_duplicate_columns(df)
        df[pd_utils.available_name(df, "source_path")] = "stdin" if args.table_name == "stdin" else path

        skip_columns = args.skip_columns
        primary_keys = args.primary_keys
        if args.business_keys:
            if not primary_keys:
                primary_keys = list(o.name for o in args.db[table].columns if o.is_pk)

            skip_columns = [*(args.skip_columns or []), *primary_keys]

        selected_columns = df.columns.to_list()
        if args.only_target_columns:
            target_columns = args.db[table].columns_dict
            selected_columns = [s for s in selected_columns if s in target_columns]
        if skip_columns:
            selected_columns = [s for s in selected_columns if s not in skip_columns]

        log.info("[%s]: %s", table, selected_columns)
        kwargs = {}
        if args.business_keys or primary_keys:
            source_table_pks = [s for s in (args.business_keys or primary_keys) if s in selected_columns]
            if source_table_pks:
                log.info("[%s]: Using %s as primary key(s)", table, ", ".join(source_table_pks))
                kwargs["pk"] = source_table_pks

        data = df.to_dict(orient="records")
        data = ({k: v for k, v in d.items() if k in selected_columns} for d in data)
        with args.db.conn:
            args.db[table].insert_all(
                data,
                alter=True,
                ignore=args.ignore,
                replace=not args.ignore,
                upsert=args.upsert,
                **kwargs,
            )


def tables_add():
    args = parse_args()
    web.requests_session(args)  # configure session
    for path in args.paths:
        table_add(args, path)


if __name__ == "__main__":
    tables_add()
