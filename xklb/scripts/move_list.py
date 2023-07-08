import argparse, shutil, tempfile
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Tuple

import humanize
from tabulate import tabulate

from xklb import consts, db, player, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library mv-list",
        usage=usage.mv_list,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default="25")
    parser.add_argument("--lower", default=4, type=int, help="Number of files per folder lower limit")
    parser.add_argument("--upper", default=4000, type=int, help="Number of files per folder upper limit")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("mount_point")
    parser.add_argument("database")
    args = parser.parse_args()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def group_by_folder(args, media) -> List[Dict]:
    d = {}
    for m in media:
        if m["path"].startswith("http"):
            continue

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
            """
        select
            path
            , size
        from media
        where 1=1
            and coalesce(time_deleted, 0)=0
        order by path
        """,
        ),
    )

    folders = group_by_folder(args, media)
    return sorted(folders, key=lambda x: x["size"] / x["count"])


def iterate_and_show_options(args, tbl) -> Tuple[List[Dict], List[Dict]]:
    vew = tbl[-int(args.limit) :] if args.limit else tbl

    vew = utils.list_dict_filter_bool(vew, keep_0=False)
    vew = utils.col_resize_percent(vew, "path", 60)
    vew = utils.col_naturalsize(vew, "size")
    print(tabulate(vew, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False))
    print(len(tbl) - len(vew), "other folders not shown")

    if args.limit:
        return tbl[-int(args.limit) :], tbl[: -int(args.limit)]
    else:
        return tbl, tbl


def move_list() -> None:
    args = parse_args()
    _total, _used, free = shutil.disk_usage(args.mount_point)

    print("Current free space:", humanize.naturalsize(free))

    data = get_table(args)

    tbl = deepcopy(data)
    cur, rest = iterate_and_show_options(args, tbl)

    data = {d["path"]: d for d in data}

    utils.set_readline_completion(list(data.keys()))

    print(
        """
██╗███╗░░██╗░██████╗████████╗██████╗░██╗░░░██╗░█████╗░████████╗██╗░█████╗░███╗░░██╗░██████╗
██║████╗░██║██╔════╝╚══██╔══╝██╔══██╗██║░░░██║██╔══██╗╚══██╔══╝██║██╔══██╗████╗░██║██╔════╝
██║██╔██╗██║╚█████╗░░░░██║░░░██████╔╝██║░░░██║██║░░╚═╝░░░██║░░░██║██║░░██║██╔██╗██║╚█████╗░
██║██║╚████║░╚═══██╗░░░██║░░░██╔══██╗██║░░░██║██║░░██╗░░░██║░░░██║██║░░██║██║╚████║░╚═══██╗
██║██║░╚███║██████╔╝░░░██║░░░██║░░██║╚██████╔╝╚█████╔╝░░░██║░░░██║╚█████╔╝██║░╚███║██████╔╝
╚═╝╚═╝░░╚══╝╚═════╝░░░░╚═╝░░░╚═╝░░╚═╝░╚═════╝░░╚════╝░░░░╚═╝░░░╚═╝░╚════╝░╚═╝░░╚══╝╚═════╝░

Type "done" when finished
Type "more" to see more files
Paste a folder (and press enter) to toggle selection
Type "*" to select all files in the most recently printed table
""",
    )

    selected_paths = set()
    while True:
        try:
            input_path = input("Paste a path: ").strip()
        except EOFError:
            break
        if input_path.lower() in ["done", "q"]:
            break

        if input_path.lower() == "more":
            cur, rest = iterate_and_show_options(args, rest)
            continue

        if input_path == "*":
            if cur:
                selected_paths.update([d["path"] for d in cur])
            else:
                selected_paths.update(data.keys())

            cur, rest = iterate_and_show_options(args, rest)
        else:
            try:
                data[input_path]
            except KeyError:
                continue

            if input_path in selected_paths:
                selected_paths.discard(input_path)
            else:
                selected_paths.add(input_path)

        # remove child paths so that the size of data is not counted twice
        temp_set = selected_paths.copy()
        for path1 in temp_set:
            for path2 in temp_set:
                if path1 != path2 and path1.startswith(path2):
                    selected_paths.discard(path1)

        selected_paths_size = sum([data[p]["size"] for p in selected_paths])
        print(
            len(selected_paths),
            "selected paths:",
            humanize.naturalsize(selected_paths_size),
            "; future free space:",
            humanize.naturalsize(selected_paths_size + free),
        )

    if selected_paths:
        temp_file = Path(tempfile.mktemp())
        with temp_file.open("w") as f:
            f.writelines("\n".join(selected_paths))

        print(
            f"""

    Folder list saved to {temp_file}. You may want to use the following command to move files to an EMPTY folder target:

        rsync -aE --xattrs --info=progress2 --no-inc-recursive --remove-source-files --files-from={temp_file} -r -vv --dry-run / jim:/free/real/estate/
        """,
        )

        if utils.confirm(f"Mark as deleted in {args.database}?"):  # type: ignore
            player.mark_media_deleted_like(args, list(selected_paths))


if __name__ == "__main__":
    move_list()
