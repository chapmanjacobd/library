import argparse, textwrap
from copy import deepcopy
from itertools import groupby
from typing import Tuple

from xklb import consts, db, player, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library search", usage=usage.search)
    parser.add_argument("--open", "--play", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--overlap", type=int, default=8, help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", default=["path", "time"], help=argparse.SUPPRESS)
    parser.add_argument("--table", action="store_true")
    parser.add_argument("--limit", "-L", "-l", help=argparse.SUPPRESS)

    parser.add_argument("--print", "-p", default="p", const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a column when printing")
    parser.add_argument("--action", default="search", help=argparse.SUPPRESS)
    parser.add_argument("--folder", action="store_true", help="Experimental escape hatch to open folder")
    parser.add_argument(
        "--folder-glob",
        "--folderglob",
        type=int,
        default=False,
        const=10,
        nargs="?",
        help="Experimental escape hatch to open a folder glob limited to x number of files",
    )

    parser.add_argument("--ignore-errors", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--online-media-only", "--online", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local-media-only", "--local", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--loop", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--override-player", "--player", "-player", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    parser.add_argument("search", nargs="*")
    args = parser.parse_args()
    args.include += args.search

    if args.cols:
        args.cols = list(utils.flatten([s.split(",") for s in args.cols]))

    sort = [player.override_sort(s) for s in args.sort]
    sort = "\n        , ".join(sort)
    args.sort = sort.replace(",,", ",")

    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def printer(args, captions) -> None:
    captions = utils.list_dict_filter_bool(captions)
    if not captions:
        utils.no_media_found()

    tbl = deepcopy(captions)
    utils.col_hhmmss(tbl, "time")

    if args.print == "p":
        print(f"{len(captions)} captions")
        for path, path_group in groupby(tbl, key=lambda x: x["path"]):
            path_group = list(path_group)
            title = path_group[0].get("title")
            print(" - ".join(utils.concat(title, path)))
            for caption in path_group:
                for line in textwrap.wrap(caption["text"], subsequent_indent=" " * 9, initial_indent=f"{caption['time']} ", width=consts.TERMINAL_SIZE.columns - 2):  # type: ignore
                    print(line)
            print()
    else:
        player.media_printer(args, captions, units="captions")


def construct_query(args) -> Tuple[str, dict]:
    m_columns = db.columns(args, "media")
    c_columns = db.columns(args, "captions")
    args.filter_sql = []
    args.filter_bindings = {}

    args.filter_sql.extend([" and " + w for w in args.where])

    table = "captions"
    if args.db["captions"].detect_fts():
        if args.include:
            args.table, search_bindings = db.fts_search_sql(
                "captions",
                fts_table=args.db["captions"].detect_fts(),
                include=args.include,
                exclude=args.exclude,
            )
            args.filter_bindings = {**args.filter_bindings, **search_bindings}
            c_columns = {**c_columns, "rank": int}
        elif args.exclude:
            db.construct_search_bindings(args, c_columns)
    else:
        db.construct_search_bindings(args, c_columns)

    cols = args.cols or ["path", "text", "time", "rank", "title"]
    args.select = [c for c in cols if c in {**c_columns, **m_columns, **{"*": "Any"}}]
    args.select_sql = "\n        , ".join(args.select)
    args.limit_sql = "LIMIT " + str(args.limit) if args.limit else ""
    query = f"""WITH c as (
        SELECT id, * FROM {table}
        WHERE 1=1
            {player.filter_args_sql(args, c_columns)}
    )
    SELECT
        {args.select_sql}
    FROM c
    JOIN media m on m.id = c.media_id
    WHERE 1=1
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        , {args.sort}
    {args.limit_sql}
    """

    return query, args.filter_bindings


def merge_captions(args, captions):
    def get_end(caption):
        return caption["time"] + (len(caption["text"]) / 4.2 / 220 * 60)

    merged_captions = []
    for path, group in groupby(
        captions,
        key=lambda x: x["path"],
    ):  # group by only does contiguous items with the same key
        group = list(group)
        merged_group = {"path": path, "title": group[0]["title"], "time": group[0]["time"], "end": get_end(group[0]), "text": group[0]["text"]}  # type: ignore
        for i in range(1, len(group)):
            end = get_end(group[i])

            if (
                abs(group[i]["time"] - merged_group["end"]) <= args.overlap  # type: ignore
                or abs(group[i]["time"] - merged_group["time"]) <= args.overlap  # type: ignore
            ):
                merged_group["end"] = end
                if group[i]["text"] not in merged_group["text"]:  # type: ignore
                    merged_group["text"] += ". " + group[i]["text"]  # type: ignore
            else:
                merged_captions.append(merged_group)
                merged_group = {
                    "path": path,
                    "time": group[i]["time"],  # type: ignore
                    "end": end,
                    "text": group[i]["text"],  # type: ignore
                }
        merged_captions.append(merged_group)

    return merged_captions


def search() -> None:
    args = parse_args()
    query, bindings = construct_query(args)
    captions = list(args.db.query(query, bindings))
    merged_captions = merge_captions(args, captions)

    if args.open:
        for d in merged_captions:
            print(d["text"])

            args.start = str(d["time"] - 2)
            args.end = str(int(d["end"] + 1.5))
            m = args.db.pop_dict("select * from media where path = ?", [d["path"]])
            args.player = player.parse(args, m)
            r = player.local_player(args, m)
            if r.returncode != 0:
                log.warning("Player exited with code %s", r.returncode)
                if args.ignore_errors:
                    return
                else:
                    raise SystemExit(r.returncode)

    else:
        printer(args, merged_captions)


if __name__ == "__main__":
    search()
