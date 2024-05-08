import argparse, sqlite3
from pathlib import Path

from xklb import usage
from xklb.utils import arggroups, argparse_utils, db_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library merge-dbs", usage=usage.merge_dbs)

    parser.add_argument(
        "--only-tables", "-t", action=argparse_utils.ArgparseList, help="Comma separated specific table(s)"
    )

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

    parser.add_argument("--where", "-w", nargs="+", action="extend", help=argparse.SUPPRESS)

    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("source_dbs", nargs="+")
    args = parser.parse_intermixed_args()

    arggroups.args_post(args, parser, create_db=True)
    return args


def merge_db(args, source_db) -> None:
    source_db = str(Path(source_db).resolve())

    s_db = db_utils.connect(args, conn=sqlite3.connect(args.database))
    for table in [s for s in s_db.table_names() if "_fts" not in s and not s.startswith("sqlite_")]:
        if args.only_tables and table not in args.only_tables:
            log.info("[%s]: Skipping %s", source_db, table)
            continue
        else:
            log.info("[%s]: %s", source_db, table)

        skip_columns = args.skip_columns
        primary_keys = args.primary_keys
        if args.business_keys:
            if not primary_keys:
                primary_keys = list(o.name for o in args.db[table].columns if o.is_pk)

            skip_columns = [*(args.skip_columns or []), *primary_keys]

        selected_columns = s_db[table].columns_dict
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

        data = s_db[table].rows_where(where=" and ".join(args.where) if args.where else None)
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


def merge_dbs() -> None:
    args = parse_args()
    for s_db in args.source_dbs:
        merge_db(args, s_db)


if __name__ == "__main__":
    merge_dbs()
