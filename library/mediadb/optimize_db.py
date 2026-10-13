from library.utils import arggroups, argparse_utils, db_utils

USAGE = {
    'optimize': """library database optimize DATABASE [--force]

    Optimize library databases

    The force flag is usually unnecessary and it can take much longer
""",
}


def optimize_db() -> None:
    parser = argparse_utils.ArgumentParser(usage=USAGE['optimize'])
    parser.add_argument("--fts", action="store_true")
    parser.add_argument("--force", "-f", action="store_true")
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    db_utils.optimize(args)
