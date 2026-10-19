from library import usage
from library.utils import arggroups, argparse_utils, db_utils


def optimize_db() -> None:
    parser = argparse_utils.ArgumentParser(usage=usage.optimize)
    parser.add_argument("--fts", action="store_true")
    parser.add_argument("--force", "-f", action="store_true")
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    db_utils.optimize(args)
