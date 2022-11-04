import argparse
from pathlib import Path

from xklb import db, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("dbs", nargs="*")
    parser.add_argument("--upsert")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def merge_db(args, source_db):
    source_db = str(Path(source_db).resolve())

    s_db = db.connect(argparse.Namespace(database=source_db, verbose=args.verbose))
    for table in [s for s in s_db.table_names() if not "_fts" in s and not s.startswith("sqlite_")]:
        log.info("[%s]: %s", source_db, table)
        data = s_db[table].rows

        with args.db.conn:
            if args.upsert:
                args.db[table].upsert_all(data, pk=args.upsert.split(","), alter=True)
            else:
                args.db[table].insert_all(data, alter=True, replace=True)


def merge_dbs():
    args = parse_args()
    for s_db in args.dbs:
        merge_db(args, s_db)


if __name__ == "__main__":
    merge_dbs()
