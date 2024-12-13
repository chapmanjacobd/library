import argparse, json

from library import usage
from library.utils import arggroups, argparse_utils, consts, sql_utils


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.search_db)
    arggroups.sql_fs(parser)
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search_table")
    parser.add_argument("search", nargs="+", action=argparse_utils.ArgparseArgsOrStdin)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=True)

    arggroups.sql_fs_post(args)
    return args


def get_table_name(args):
    if args.search_table in args.db.table_names():
        return args.search_table

    valid_tables = []
    for s in args.db.table_names():
        if "_fts_" in s or s.endswith("_fts") or "sqlite_stat" in s:
            continue
        valid_tables.append(s)

    matching_tables = []
    for s in valid_tables:
        if s.startswith(args.search_table):
            matching_tables.append(s)

    if len(matching_tables) == 1:
        return matching_tables[0]

    msg = f"Table {args.search_table} does not exist in {args.database}"
    raise ValueError(msg)


def search_db() -> None:
    args = parse_args()
    args.search_table = get_table_name(args)

    args.filter_sql = []
    args.filter_bindings = {}

    columns = args.db[args.search_table].columns_dict
    search_sql, search_bindings = sql_utils.construct_search_bindings(
        include=args.include,
        exclude=args.exclude,
        columns=columns,
        exact=args.exact,
        flexible_search=args.flexible_search,
    )
    args.filter_sql.extend(search_sql)
    args.filter_bindings = {**args.filter_bindings, **search_bindings}

    if args.delete_rows:  # TODO: replace with media_printer?
        deleted_count = 0
        with args.db.conn:
            cursor = args.db.conn.execute(
                f"DELETE FROM {args.search_table} WHERE 1=1 " + " ".join(args.filter_sql),
                args.filter_bindings,
            )
            deleted_count += cursor.rowcount
        print(f"Deleted {deleted_count} rows")
    elif args.mark_deleted:
        modified_row_count = 0
        with args.db.conn:
            cursor = args.db.conn.execute(
                f"UPDATE {args.search_table} SET time_deleted={consts.APPLICATION_START} WHERE 1=1 "
                + " ".join(args.filter_sql),
                args.filter_bindings,
            )
            modified_row_count += cursor.rowcount
        print(f"Marked {modified_row_count} rows as deleted")
    else:
        for row in args.db.execute_returning_dicts(
            f"SELECT * FROM {args.search_table} WHERE 1=1 " + " ".join(args.filter_sql),
            args.filter_bindings,
        ):
            print(json.dumps(row))
