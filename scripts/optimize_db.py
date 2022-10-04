import argparse

from xklb import db, utils
from xklb.utils import log


def optimize_db():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("database", nargs="?", default="video.db")
    args = parser.parse_args()
    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    db.optimize(args)
