import argparse
from copy import deepcopy
from typing import List

from rich import print, prompt
from tabulate import tabulate

from xklb import consts, db, utils
from xklb.utils import log


def get_duplicates(args) -> List[dict]:
    query = f"""
    SELECT
        m1.path keep_path
        , m2.path duplicate_path
        , m2.title
    FROM
        media m1
    JOIN media m2 on 1=1
        and m2.path != m1.path
        and m1.path like '%'|| m2.id ||'%'
        and m2.path like 'http%'
        and m1.id is null
        and m1.ie_key != m2.ie_key
    WHERE 1=1
        and m1.time_deleted = 0 and m2.time_deleted = 0
        and (m2.duration is null or m2.duration = 0 or m1.duration >= m2.duration - 4)
        and (m2.duration is null or m2.duration = 0 or m1.duration <= m2.duration + 4)
    ORDER BY 1=1
        , length(m1.path)-length(REPLACE(m1.path, '/', '')) desc
        , length(m1.path)-length(REPLACE(m1.path, '.', ''))
        , length(m1.path)
        , m1.time_modified desc
        , m1.time_created desc
        , m1.duration desc
        , m1.path desc
    """

    media = list(args.db.query(query))

    return media


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default=100)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def get_dict(args, path) -> dict:
    known = list(args.db.query("select * from media where path=?", [path]))[0]
    return utils.dict_filter_bool(known)


def merge_online_local() -> None:
    args = parse_args()
    duplicates = get_duplicates(args)
    duplicates_count = len(duplicates)

    tbl = deepcopy(duplicates)
    tbl = tbl[: int(args.limit)]
    tbl = utils.col_resize(tbl, "keep_path", 30)
    tbl = utils.col_resize(tbl, "duplicate_path", 30)
    tbl = utils.col_naturalsize(tbl, "duplicate_size")
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))

    print(f"{duplicates_count} duplicates found (showing first {args.limit})")

    if duplicates and prompt.Confirm.ask("Merge duplicates?", default=False):  # type: ignore
        print("Merging...")

        merged = []
        for d in duplicates:
            fspath = d["keep_path"]
            webpath = d["duplicate_path"]
            if fspath in merged:
                continue

            tube_entry = get_dict(args, webpath)
            fs_tags = get_dict(args, fspath)
            if fs_tags['time_modified'] is None or fs_tags['time_modified'] == 0:
                fs_tags['time_modified'] = consts.NOW
            if fs_tags['time_downloaded'] is None or fs_tags['time_downloaded'] == 0:
                fs_tags['time_downloaded'] = consts.NOW

            entry = {**tube_entry, **fs_tags, "webpath": webpath}
            args.db["media"].insert(entry, pk="path", alter=True, replace=True)  # type: ignore
            args.db["media"].delete(webpath)
            merged.append(fspath)

        print(len(merged), "merged")


if __name__ == "__main__":
    merge_online_local()
