from datetime import datetime, timezone
from pathlib import Path

from xklb.__main__ import library as lb
from xklb.utils import argparse_utils, consts, db_utils
from xklb.utils.objects import NoneSpace


def take5():
    num = 0
    while num < 5:
        yield num
        num += 1


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


def connect_db_args(db_path) -> NoneSpace:
    return NoneSpace(db=db_utils.connect(NoneSpace(database=db_path, verbose=0)))


def ignore_tz(s):
    return datetime.fromtimestamp(s, timezone.utc).replace(tzinfo=None).timestamp()


def get_default_args(*funcs):
    parser = argparse_utils.ArgumentParser()
    for func in funcs:
        func(parser)
    defaults = {action.dest: action.default for action in parser._actions}
    return defaults


links_db = "tests/data/links.db"
if not Path(links_db).exists():
    lb(
        [
            "links-add",
            links_db,
            "-c=p1",
            "--insert-only",
            "https://site0",
            "https://site1",
            "https://site2",
            "https://site3",
            "https://site4",
            "https://site5",
            "https://site6",
            "https://site7",
            "https://site8",
        ],
    )

v_db = "tests/data/video.db"
if not Path(v_db).exists():
    lb(["fs_add", v_db, "--scan-subtitles", "tests/data/", "-E", "Youtube"])
    lb(["linksdb", v_db, "--insert-only", "https://test/?tags%5B%5D="])


tube_db = "tests/data/tube.db"
if not consts.VOLKSWAGEN and not Path(tube_db).exists():
    lb(
        [
            "tube_add",
            tube_db,
            "--extra",
            "--extractor-config",
            "TEST1=1 TEST2=2",
            "https://youtube.com/playlist?list=PLVoczRgDnXDLWV1UJ_tO70VT_ON0tuEdm",
        ]
    )
