import argparse
from pathlib import Path

from xklb import usage
from xklb.utils import arg_utils, db_utils, objects
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library dedupe-dbs", usage=usage.dedupe_db)
    parser.add_argument("--skip-upsert", action="store_true")
    parser.add_argument("--skip-0", action="store_true")
    parser.add_argument("--only-columns", action=arg_utils.ArgparseList, help="Comma separated column names to upsert")
    parser.add_argument("--primary-keys", "--pk", action=arg_utils.ArgparseList, help="Comma separated primary keys")
    parser.add_argument(
        "--business-keys",
        "--bk",
        action=arg_utils.ArgparseList,
        required=True,
        help="Comma separated business keys",
    )
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("table")
    args = parser.parse_intermixed_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def dedupe_rows(args, tablename, primary_keys, business_keys):
    with args.db.conn:
        args.db.conn.execute(
            f"""
            DELETE FROM {tablename}
            WHERE ({','.join(primary_keys)}) NOT IN (
                SELECT {','.join(f"MIN({col}) AS {col}" for col in primary_keys)}
                FROM {tablename}
                GROUP BY {','.join(business_keys)}
            )
            """,
        )


def dedupe_db() -> None:
    args = parse_args()

    upsert_columns = args.only_columns
    target_columns = args.db[args.table].columns_dict
    if not args.primary_keys:
        args.primary_keys = list(o.name for o in args.db[args.table].columns if o.is_pk)
    if not upsert_columns:
        upsert_columns = [s for s in target_columns if s not in args.primary_keys + args.business_keys]

    missing_columns = [s for s in upsert_columns if s not in target_columns]
    if missing_columns:
        raise ValueError("At least one upsert column not available in target table: %s", missing_columns)

    if set(upsert_columns).intersection(args.primary_keys):
        raise ValueError("One of your primary keys is also an upsert column. I don't think that will work...?")
    if set(upsert_columns).intersection(args.business_keys):
        raise ValueError("One of your business keys is also an upsert column. That might not do anything bad but...")
    if len(args.primary_keys) == 0:
        raise ValueError("No primary keys found. Try to re-run with --pk rowid ?")

    if not args.skip_upsert:
        log.info("Upserting data in %s", ",".join(upsert_columns))

        for col in upsert_columns:
            data = list(
                args.db.query(
                    f"""
                    SELECT {','.join([*args.business_keys, col])}
                    FROM {args.table}
                    WHERE {f'NULLIF({col}, 0)' if args.skip_0 else col} IS NOT NULL
                    AND ({','.join(args.business_keys)}) IN (
                        SELECT {','.join(args.business_keys)}
                        FROM {args.table}
                        WHERE {col} IS NULL
                    )
                    ORDER BY {','.join(args.primary_keys)}
                    """,
                ),
            )
            log.info("%s (%s rows)", col, len(data))

            with args.db.conn:

                def gen_where_sql(row):
                    return " AND ".join([f"{key} = {args.db.quote(row[key])}" for key in args.business_keys])

                def gen_update_sql(row):
                    return f"UPDATE {args.table} SET {col} = {args.db.quote(row[col])} WHERE {gen_where_sql(row)};"

                args.db.conn.executescript("\n".join([gen_update_sql(row) for row in data]))

    dedupe_rows(args, args.table, primary_keys=args.primary_keys, business_keys=args.business_keys)


if __name__ == "__main__":
    dedupe_db()
