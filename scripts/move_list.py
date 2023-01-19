import argparse, shutil
from copy import deepcopy
from typing import List

import humanize
from tabulate import tabulate

from xklb import db, utils
from xklb.utils import log


def group_by_folder(args, media):
    d = {}
    for m in media:
        p = m["path"].split("/")
        while len(p) >= 3:
            p.pop()
            parent = "/".join(p) + "/"

            if d.get(parent):
                d[parent]["size"] += m["size"]
                d[parent]["count"] += 1
            else:
                d[parent] = {
                    "size": m["size"],
                    "count": 1,
                }

    for path, pdict in list(d.items()):
        if any([pdict["count"] < args.lower, pdict["count"] > args.upper]):
            d.pop(path)

    return [{**v, "path": k} for k, v in d.items()]


def get_table(args) -> List[dict]:
    media = list(
        args.db.query(
            f"""
        select
            path
            , size
        from media
        where 1=1
            and time_downloaded > 0
        order by path
        """
        )
    )

    folders = group_by_folder(args, media)
    return sorted(folders, key=lambda x: x["size"] / x["count"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default="40")
    parser.add_argument("--lower", default=4, type=int, help="Number of files per folder lower limit")
    parser.add_argument("--upper", default=4000, type=int, help="Number of files per folder upper limit")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("mount_point")
    parser.add_argument("database")
    args = parser.parse_args()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def print_some(args, tbl):
    if args.limit:
        vew = tbl[-int(args.limit) :]
    else:
        vew = tbl

    vew = utils.list_dict_filter_bool(vew, keep_0=False)
    vew = utils.col_resize(vew, "path", 60)
    vew = utils.col_naturalsize(vew, "size")
    print(tabulate(vew, tablefmt="fancy_grid", headers="keys", showindex=False))

    return tbl[: -int(args.limit)]


def move_list() -> None:
    args = parse_args()
    _total, _used, free = shutil.disk_usage(args.mount_point)

    print("Current free space:", humanize.naturalsize(free))

    data = get_table(args)

    tbl = deepcopy(data)
    tbl = print_some(args, tbl)

    data = {d["path"]: d for d in data}

    selected_paths = set()
    while True:
        try:
            input_path = input('Paste a path (type "more" for more options and "done" when finished): ')
        except EOFError:
            break

        if input_path.lower() in ["done", "q"]:
            break
        if input_path.lower() == "more":
            tbl = print_some(args, tbl)

        try:
            data[input_path]
        except KeyError:
            continue

        if input_path in selected_paths:
            selected_paths.discard(input_path)
        else:
            selected_paths.add(input_path)

        # remove child paths so that the size of data is not counted twice
        paths = sorted(selected_paths)
        for i in range(len(paths) - 1):
            if paths[i + 1].startswith(paths[i]):
                selected_paths.discard(paths[i + 1])

        selected_paths_size = sum([data[p]["size"] for p in selected_paths])
        print(
            len(selected_paths),
            "selected paths:",
            humanize.naturalsize(selected_paths_size),
            "; future mount size:",
            humanize.naturalsize(selected_paths_size + free),
        )

    if len(selected_paths) > 0:
        print("\n\nSelected paths:\n")
        print("\n".join(selected_paths))


if __name__ == "__main__":
    move_list()
