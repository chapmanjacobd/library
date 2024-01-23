import argparse, webbrowser
from pathlib import Path
from time import sleep
from typing import Tuple

from xklb import db_media, usage
from xklb.media import media_printer
from xklb.utils import arg_utils, consts, db_utils, iterables, objects, processes
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library open-links",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        usage=usage.open_links,
    )
    parser.add_argument("--path", action="store_true")
    parser.add_argument("--title", "-S", action="store_true")
    parser.add_argument("--title-prefix", "--prefix", nargs="+", action="extend")

    parser.add_argument("--sort", "-u", nargs="+")
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[])
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[])
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[])
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--print", "-p", default="", const="p", nargs="?")
    parser.add_argument("--category", "-c")
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a column when printing")
    parser.add_argument(
        "--delete",
        "--remove",
        "--erase",
        "--rm",
        "-rm",
        action="store_true",
        help="Delete matching rows",
    )
    parser.add_argument("--limit", "-L", "-l", "-n", type=int, default=7)
    parser.add_argument("--skip")

    parser.add_argument("--cluster-sort", "--cluster", "-C", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--clusters", "--n-clusters", type=int, help="Number of KMeans clusters")
    parser.add_argument("--related", "-R", action="count", default=0, help=argparse.SUPPRESS)

    parser.add_argument("--db", "-db")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = "open-links"

    args.include += args.search
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if not args.title_prefix:
        args.title_prefix = ["https://www.google.com/search?q="]

    if args.db:
        args.database = args.db

    if args.sort:
        args.sort = [arg_utils.override_sort(s) for s in args.sort]
        args.sort = " ".join(args.sort)

    if args.cols:
        args.cols = list(iterables.flatten([s.split(",") for s in args.cols]))

    if args.delete:
        args.print += "d"

    if args.db:
        args.database = args.db
    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def links_include_sql(x) -> str:
    return f"""and (
    path like :include{x}
    OR title like :include{x}
)"""


def links_exclude_sql(x) -> str:
    return f"""and (
    path not like :exclude{x}
    AND title not like :exclude{x}
)"""


def construct_links_query(args) -> Tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")

    args.filter_sql = []
    args.filter_bindings = {}

    args.filter_sql.extend([" and " + w for w in args.where])

    for idx, inc in enumerate(args.include):
        args.filter_sql.append(links_include_sql(idx))
        if args.exact:
            args.filter_bindings[f"include{idx}"] = inc
        else:
            args.filter_bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        args.filter_sql.append(links_exclude_sql(idx))
        if args.exact:
            args.filter_bindings[f"exclude{idx}"] = exc
        else:
            args.filter_bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"

    if args.category:
        args.filter_sql.append("AND category like :category")
        if args.exact:
            args.filter_bindings[f"category"] = args.category
        else:
            args.filter_bindings[f"category"] = "%" + args.category.replace(" ", "%").replace("%%", " ") + "%"

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""SELECT path
        {', title' if 'title' in m_columns else ''}
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM media
    WHERE 1=1
        AND COALESCE(time_deleted, 0)=0
        AND path like "http%"
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        {', ' + args.sort if args.sort else ''}
        , time_modified = 0 DESC
        {', ROW_NUMBER() OVER ( PARTITION BY hostname )' if 'hostname' in m_columns else ''}
        {', ROW_NUMBER() OVER ( PARTITION BY category )' if 'category' in m_columns else ''}
        , random()
    {LIMIT} {OFFSET}
    """

    return query, args.filter_bindings


def play(args, path, url) -> None:
    webbrowser.open(url, 2, autoraise=False)
    with args.db.conn:
        args.db.conn.execute("UPDATE media SET time_modified = coalesce(time_modified,0) +1 WHERE path = ?", [path])


def make_souffle(args, media):
    pan = []
    for m in media:
        if args.title:
            for pre in args.title_prefix:
                url = pre + (m.get("title") or m["path"])
                pan.append({**m, "url": url})

        if not args.title or args.path:
            pan.append({**m, "url": m["path"]})

    return pan


def open_links() -> None:
    args = parse_args()

    query, bindings = construct_links_query(args)
    media = list(args.db.query(query, bindings))

    if args.related >= consts.RELATED:
        media = db_media.get_related_media(args, media[0])

    if args.cluster_sort:
        from xklb.scripts.cluster_sort import cluster_dicts

        media = cluster_dicts(args, media)

    media = make_souffle(args, media)

    if args.print:
        media_printer.media_printer(args, media)
        return

    if not media:
        processes.no_media_found()

    for m in media:
        play(args, m["path"], m["title"])

        if len(media) >= consts.MANY_LINKS:
            sleep(0.3)
