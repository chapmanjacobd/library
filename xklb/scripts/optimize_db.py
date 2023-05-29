import argparse

from xklb import db, usage, utils
from xklb.utils import log


def optimize_db() -> None:
    parser = argparse.ArgumentParser(prog="library optimize", usage=usage.optimize)
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("database")
    args = parser.parse_args()
    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    db.optimize(args)
