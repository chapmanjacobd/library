import argparse
from pathlib import Path

from xklb import db, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library dedupe-dbs", usage=usage.dedupe_db)
    parser.add_argument(
        "--primary-keys", "--pk", action=utils.ArgparseList, required=True, help="Comma separated primary keys"
    )
    parser.add_argument(
        "--business-keys", "--bk", action=utils.ArgparseList, required=True, help="Comma separated business keys"
    )
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("table")
    parser.add_argument("upsert_columns", action=utils.ArgparseList, help="Comma separated column names to upsert")
    args = parser.parse_intermixed_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def dedupe_db() -> None:
    args = parse_args()

    target_columns = args.db[args.table].columns_dict
    missing_columns = [s for s in args.upsert_columns if s not in target_columns]
    if missing_columns:
        raise ValueError('At least one upsert column not available in target table: %s', missing_columns)

    if set(args.upsert_columns).intersection(args.primary_keys):
        raise ValueError("One of your primary keys is also an upsert column. I don't think that will work...?")
    if set(args.upsert_columns).intersection(args.business_keys):
        raise ValueError("One of your business keys is also an upsert column. That might not do anything bad but you should spend some time with self-reflexivity")

    where_business = ' AND '.join([f'{key} = ?' for key in args.business_keys])
    with args.db.conn:
        for col in args.upsert_columns:
            data = args.db.query(
                f'''
                SELECT {col}
                FROM {args.table}
                WHERE {col} IS NOT NULL
                '''
            )
            for row in data:
                args.db.conn.execute(
                    f'''
                    UPDATE {args.table}
                    SET {col} = ?
                    WHERE {where_business}
                    ''',
                    [row[col], *[row[k] for k in args.business_keys]],
                )

        args.db.conn.execute(
            f'''
            DELETE FROM {args.table}
            WHERE {','.join(args.primary_keys)} NOT IN (
                SELECT {','.join(f"MIN({col}) AS {col}" for col in args.primary_keys)}
                FROM {args.table}
                GROUP BY {','.join(args.business_keys)}
            )
            '''
        )

if __name__ == "__main__":
    dedupe_db()
