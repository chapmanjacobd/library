from pathlib import Path

from library.utils import arg_utils, arggroups, argparse_utils, db_utils
from library.utils.log_utils import log

USAGE = {
    'row_add': """library database add row DATABASE [--table-name TABLE_NAME] --COLUMN-NAME VALUE

    Add a row to sqlite

        library database add row t.db --test_b 1 --test-a 2

        ### media (1 rows)
        |   test_b |   test_a |
        |----------|----------|
        |        1 |        2 |
""",
}


def parse_utils():
    parser = argparse_utils.ArgumentParser(description="Add arbitrary rows to a SQLite db", usage=USAGE['row_add'])
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
