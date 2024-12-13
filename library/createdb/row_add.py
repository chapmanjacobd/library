from pathlib import Path

from library import usage
from library.utils import arg_utils, arggroups, argparse_utils, db_utils
from library.utils.log_utils import log


def parse_utils():
    parser = argparse_utils.ArgumentParser(description="Add arbitrary rows to a SQLite db", usage=usage.row_add)
    parser.add_argument("--table-name", "--table", "-t", default="media")
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="""Control the level of logging verbosity
-v     # info
-vv    # debug
-vvv   # debug, with SQL query printing
-vvvv  # debug, with external libraries logging""",
    )

    arggroups.database(parser)
    args, unknown_args = parser.parse_known_args()
    Path(args.database).touch()
    args.db = db_utils.connect(args)
    return args, unknown_args


def row_add():
    args, unknown_args = parse_utils()

    kwargs = arg_utils.dict_from_unknown_args(unknown_args)
    if not kwargs:
        log.error("No data given via arguments")
        raise SystemExit(2)
    args.db[args.table_name].insert(kwargs, alter=True)
