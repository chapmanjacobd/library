import argparse

from xklb import usage
from xklb.utils import arggroups, db_utils, objects
from xklb.utils.log_utils import log


def optimize_db() -> None:
    parser = argparse.ArgumentParser(prog="library optimize", usage=usage.optimize)
    parser.add_argument("--fts", action="store_true")
    parser.add_argument("--force", "-f", action="store_true")
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_args()

    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))

    db_utils.optimize(args)
