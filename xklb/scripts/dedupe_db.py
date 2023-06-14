import argparse
from pathlib import Path

from xklb import db, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library dedupe-dbs", usage=usage.dedupe_db)
    parser.add_argument("--skip-0", action="store_true")
    parser.add_argument("--only-columns", action=utils.ArgparseList, help="Comma separated column names to upsert")
    parser.add_argument("--primary-keys", "--pk", action=utils.ArgparseList, help="Comma separated primary keys")
    parser.add_argument(
        "--business-keys", "--bk", action=utils.ArgparseList, required=True, help="Comma separated business keys"
    )
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("table")
    args = parser.parse_intermixed_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


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

    for col in upsert_columns:
        data = list(
            args.db.query(
                f"""
                SELECT {','.join(args.business_keys + [col])}
                FROM {args.table}
                WHERE {f'NULLIF({col}, 0)' if args.skip_0 else col} IS NOT NULL
                ORDER BY {','.join(args.primary_keys)}
                """
            )
        )
        log.info("%s (%s rows)", col, len(data))

        with args.db.conn:
            args.db.conn.executescript(
                "\n".join(
                    [
                        f"UPDATE {args.table} SET {col} = {args.db.quote(row[col])} WHERE {' AND '.join([f'{key} = {args.db.quote(row[key])}' for key in args.business_keys])};"
                        for row in data
                    ]
                )
            )

    with args.db.conn:
        args.db.conn.execute(
            f"""
            DELETE FROM {args.table}
            WHERE ({','.join(args.primary_keys)}) NOT IN (
                SELECT {','.join(f"MIN({col}) AS {col}" for col in args.primary_keys)}
                FROM {args.table}
                GROUP BY {','.join(args.business_keys)}
            )
            """
        )


if __name__ == "__main__":
    dedupe_db()
