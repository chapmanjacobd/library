import argparse, json
from pathlib import Path

from xklb import usage
from xklb.utils import consts, db_utils, objects
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library search-db", usage=usage.search_db)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--flexible-search", "--or", "--flex", action="store_true")
    parser.add_argument(
        "--delete",
        "--remove",
        "--erase",
        "--rm",
        "-rm",
        action="store_true",
        help="Delete matching rows",
    )
    parser.add_argument("--soft-delete", action="store_true", help="Mark matching rows as deleted")

    parser.add_argument("database")
    parser.add_argument("table")
    parser.add_argument("search", nargs="+")
    args = parser.parse_intermixed_args()

    args.include += args.search
    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def get_table_name(args):
    if args.table in args.db.table_names():
        return args.table

    valid_tables = []
    for s in args.db.table_names():
        if "_fts_" in s or s.endswith("_fts") or "sqlite_stat" in s:
            continue
        valid_tables.append(s)

    matching_tables = []
    for s in valid_tables:
        if s.startswith(args.table):
            matching_tables.append(s)

    if len(matching_tables) == 1:
        return matching_tables[0]

    msg = f"Table {args.table} does not exist in {args.database}"
    raise ValueError(msg)


def search_db() -> None:
    args = parse_args()
    args.table = get_table_name(args)

    args.filter_sql = []
    args.filter_bindings = {}

    columns = args.db[args.table].columns_dict
    db_utils.construct_search_bindings(args, columns)

    if args.delete:
        deleted_count = 0
        with args.db.conn:
            cursor = args.db.conn.execute(
                f"DELETE FROM {args.table} WHERE 1=1 " + " ".join(args.filter_sql),
                args.filter_bindings,
            )
            deleted_count += cursor.rowcount
        print(f"Deleted {deleted_count} rows")
    elif args.soft_delete:
        modified_row_count = 0
        with args.db.conn:
            cursor = args.db.conn.execute(
                f"UPDATE {args.table} SET time_deleted={consts.APPLICATION_START} WHERE 1=1 "
                + " ".join(args.filter_sql),
                args.filter_bindings,
            )
            modified_row_count += cursor.rowcount
        print(f"Marked {modified_row_count} rows as deleted")
    else:
        for row in args.db.execute_returning_dicts(
            f"SELECT * FROM {args.table} WHERE 1=1 " + " ".join(args.filter_sql),
            args.filter_bindings,
        ):
            print(json.dumps(row))


if __name__ == "__main__":
    search_db()
