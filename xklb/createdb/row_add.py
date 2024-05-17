from xklb import usage
from xklb.utils import arggroups, argparse_utils, nums
from xklb.utils.log_utils import log


def parse_utils():
    parser = argparse_utils.ArgumentParser(description="Add arbitrary rows to a SQLITE db", usage=usage.row_add)
    parser.add_argument("--table-name", "--table", "-t", default="media")
    arggroups.debug(parser)

    arggroups.database(parser)
    args, unknown_args = parser.parse_known_args()
    arggroups.args_post(args, parser, create_db=True)
    return args, unknown_args


def parse_unknown_args_to_dict(unknown_args):
    kwargs = {}
    key = None
    values = []

    def get_val():
        if len(values) == 1:
            return nums.safe_int_float_str(values[0])
        else:
            return " ".join(values)

    for arg in unknown_args:
        if arg.startswith("--") or arg.startswith("-"):
            if key is not None:
                kwargs[key] = get_val()  # previous values
                values.clear()
            # Process the new key
            key = arg.strip("-").replace("-", "_")
        else:
            values.append(arg)

    if len(values) > 0:
        kwargs[key] = get_val()

    return kwargs


def row_add():
    args, unknown_args = parse_utils()

    kwargs = parse_unknown_args_to_dict(unknown_args)
    if not kwargs:
        log.error("No data given via arguments")
        raise SystemExit(2)
    args.db[args.table_name].insert(kwargs, alter=True)
