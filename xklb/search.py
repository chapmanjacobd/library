import argparse, textwrap
from copy import deepcopy
from itertools import groupby

from xklb import db_media, usage
from xklb.media import media_player, media_printer
from xklb.utils import arg_utils, consts, db_utils, iterables, objects, printing, processes
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library search", usage=usage.search)
    parser.add_argument("--open", "--play", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--overlap", type=int, default=8, help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--flexible-search", "--or", "--flex", action="store_true")
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
    args = parser.parse_intermixed_args()
    args.include += args.search

    if args.cols:
        args.cols = list(iterables.flatten([s.split(",") for s in args.cols]))

    sort = [arg_utils.override_sort(s) for s in args.sort]
    sort = "\n        , ".join(sort)
    args.sort = sort.replace(",,", ",")

    if args.db:
        args.database = args.db
    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def printer(args, captions) -> None:
    captions = iterables.list_dict_filter_bool(captions)
    if not captions:
        processes.no_media_found()

    tbl = deepcopy(captions)
    printing.col_hhmmss(tbl, "time")

    if args.print == "p":
        print(f"{len(captions)} captions")
        for path, path_group in groupby(tbl, key=lambda x: x["path"]):
            path_group = list(path_group)
            title = path_group[0].get("title")
            print(" - ".join(iterables.concat(title, path)))
            for caption in path_group:
                for line in textwrap.wrap(caption["text"], subsequent_indent=" " * 9, initial_indent=f"{caption['time']} ", width=consts.TERMINAL_SIZE.columns - 2):  # type: ignore
                    print(line)
            print()
    else:
        media_printer.media_printer(args, captions, units="captions")


def construct_query(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    c_columns = db_utils.columns(args, "captions")
    args.filter_sql = []
    args.filter_bindings = {}

    args.filter_sql.extend([" and " + w for w in args.where])

    table = "captions"
    cols = args.cols or ["path", "text", "time", "title"]

    is_fts = args.db["captions"].detect_fts()
    if is_fts and args.include:
        table, search_bindings = db_utils.fts_search_sql(
            "captions",
            fts_table=is_fts,
            include=args.include,
            exclude=args.exclude,
            flexible=args.flexible_search,
        )
        args.filter_bindings = {**args.filter_bindings, **search_bindings}
        c_columns = {**c_columns, "rank": int}
        cols.append("id")
        cols.append("rank")
    else:
        db_utils.construct_search_bindings(args, ["text"])

    args.select = [c for c in cols if c in {**c_columns, **m_columns, **{"*": "Any"}}]

    select_sql = "\n        , ".join(args.select)
    limit_sql = "LIMIT " + str(args.limit) if args.limit else ""
    query = f"""WITH c as (
        SELECT * FROM {table}
        WHERE 1=1
            {db_media.filter_args_sql(args, c_columns)}
    )
    SELECT
        {select_sql}
    FROM c
    JOIN media m on m.id = c.media_id
    WHERE 1=1
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        , {args.sort}
    {limit_sql}
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
        pl = media_player.MediaPrefetcher(args, merged_captions)
        pl.fetch()
        while pl.remaining:
            d = pl.get_m()
            if d:
                print(d["text"])
                m = args.db.pop_dict("select * from media where path = ?", [d["path"]])
                m["player"].extend([f'--start={d["time"] - 2}', f'--end={int(d["end"] + 1.5)}'])
                r = media_player.single_player(args, m)
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
