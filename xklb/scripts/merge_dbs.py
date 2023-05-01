import argparse
from pathlib import Path

from xklb import db, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library merge-dbs",
        usage="""library merge-dbs DEST_DB SOURCE_DB ... [--upsert pk1[,pk2]]

    Merge database data and tables

        lb merge-dbs video.db tv.db movies.db
        lb merge-dbs audio.db music.db podcasts.db
""",
    )
    parser.add_argument("database")
    parser.add_argument("source_dbs", nargs="+")
    parser.add_argument("--upsert")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_intermixed_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def merge_db(args, source_db) -> None:
    source_db = str(Path(source_db).resolve())

    s_db = db.connect(argparse.Namespace(database=source_db, verbose=args.verbose))
    for table in [s for s in s_db.table_names() if "_fts" not in s and not s.startswith("sqlite_")]:
        log.info("[%s]: %s", source_db, table)
        data = s_db[table].rows

        with args.db.conn:
            if args.upsert:
                args.db[table].upsert_all(data, pk=args.upsert.split(","), alter=True)
            else:
                args.db[table].insert_all(data, alter=True, replace=True)


def merge_dbs() -> None:
    args = parse_args()
    for s_db in args.source_dbs:
        merge_db(args, s_db)


if __name__ == "__main__":
    merge_dbs()
