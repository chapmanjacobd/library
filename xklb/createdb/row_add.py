from xklb import usage
from xklb.utils import arg_utils, arggroups, argparse_utils
from xklb.utils.log_utils import log


def parse_utils():
    parser = argparse_utils.ArgumentParser(description="Add arbitrary rows to a SQLITE db", usage=usage.row_add)
    parser.add_argument("--table-name", "--table", "-t", default="media")
    arggroups.debug(parser)

    arggroups.database(parser)
    args, unknown_args = parser.parse_known_args()
    arggroups.args_post(args, parser, create_db=True)
    return args, unknown_args


def row_add():
    args, unknown_args = parse_utils()

    kwargs = arg_utils.dict_from_unknown_args(unknown_args)
    if not kwargs:
        log.error("No data given via arguments")
        raise SystemExit(2)
    args.db[args.table_name].insert(kwargs, alter=True)
