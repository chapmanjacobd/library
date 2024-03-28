import argparse
from pathlib import Path

from xklb import usage
from xklb.utils import db_utils


def parse_unknown_args_to_dict(unknown_args):
    kwargs = {}
    for i in range(0, len(unknown_args), 2):
        key = unknown_args[i]
        if key.startswith("--"):
            key = key[2:]
        elif key.startswith("-"):
            key = key[1:]

        key = key.replace("-", "_")
        value = unknown_args[i + 1]
        kwargs[key] = value

    return kwargs


def add_row():
    parser = argparse.ArgumentParser(description="Add arbitrary rows to a SQLITE db", usage=usage.add_row)
    parser.add_argument("--table-name", default="media")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    args, unknown_args = parser.parse_known_args()

    Path(args.database).touch()
    args.db = db_utils.connect(args)

    kwargs = parse_unknown_args_to_dict(unknown_args)
    args.db[args.table_name].insert(kwargs, alter=True)
