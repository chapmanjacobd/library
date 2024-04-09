import argparse
from datetime import datetime, timezone
from pathlib import Path

from xklb.utils import db_utils


def p(string):
    return str(Path(string))


def filter_query_param(r1, r2):
    if r1 == r2:
        return True

    query1 = dict(r1.query)
    query2 = dict(r2.query)

    for k in ["key", "api_key"]:
        query1.pop(k, None)
        query2.pop(k, None)

    return query1 == query2


def connect_db_args(db_path):
    return argparse.Namespace(db=db_utils.connect(argparse.Namespace(database=db_path, verbose=0)))


def ignore_tz(s):
    return datetime.fromtimestamp(s, timezone.utc).replace(tzinfo=None).timestamp()
