import argparse, shlex, webbrowser
from pathlib import Path
from time import sleep
from typing import Tuple

from xklb import db_media, history, usage
from xklb.media import media_printer
from xklb.utils import arg_utils, consts, db_utils, iterables, objects, processes, web
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

    parser.add_argument("--online-media-only", "--online", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local-media-only", "--local", action="store_true", help=argparse.SUPPRESS)

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
    parser.add_argument("--limit", "-L", "-l", "-n")
    parser.add_argument("--skip")

    parser.add_argument("--cluster-sort", "--cluster", "-C", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--print-groups", "--groups", "-g", action="store_true", help="Print groups")
    parser.add_argument("--clusters", "--n-clusters", type=int, help="Number of KMeans clusters")
    parser.add_argument("--related", "-R", action="count", default=0, help=argparse.SUPPRESS)

    parser.add_argument("--browser")
    parser.add_argument("--db", "-db")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = consts.SC.open_links
    args.defaults = []

    arg_utils.parse_args_limit(args)

    args.include += args.search
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if not args.title_prefix:
        args.title_prefix = ["https://www.google.com/search?q=%"]
    args.title_prefix = [s if "%" in s else s + "%" for s in args.title_prefix]

    if args.browser:
        args.browser = shlex.split(args.browser)

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

    limit_sql = "LIMIT " + str(args.limit) if args.limit and not args.cluster_sort else ""
    offset_sql = f"OFFSET {args.skip}" if args.skip and limit_sql else ""

    args.select = ["path"]
    if args.cols:
        args.select.extend(args.cols)
    for s in ["title", "hostname", "category"]:
        if s in m_columns:
            args.select.append(s)

    query = f"""WITH m as (
            SELECT
                {', '.join(args.select) if args.select else ''}
                , COALESCE(MAX(h.time_played), 0) time_last_played
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , time_deleted
            FROM media
            LEFT JOIN history h on h.media_id = media.id
            WHERE COALESCE(time_deleted, 0)=0
            GROUP BY media.id
        )
        SELECT
        {', '.join(args.select) if args.select else ''}
        {", time_last_played" if args.print else ''}
    FROM m
    WHERE 1=1
        AND COALESCE(time_deleted, 0)=0
        {'AND path like "http%"' if args.online_media_only else ''}
        {'AND path not like "http%"' if args.local_media_only else ''}
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        {', ' + args.sort if args.sort else ''}
        , play_count
        {', ROW_NUMBER() OVER ( PARTITION BY hostname )' if 'hostname' in m_columns else ''}
        {', ROW_NUMBER() OVER ( PARTITION BY category )' if 'category' in m_columns else ''}
        , random()
    {limit_sql} {offset_sql}
    """

    return query, args.filter_bindings


def play(args, path, url) -> None:
    if args.browser:
        processes.cmd(*args.browser, url)
    else:
        webbrowser.open(url, 2, autoraise=False)
    history.add(args, [path], time_played=consts.today_stamp(), mark_done=True)


def make_souffle(args, media):
    pan = []

    urls = set()
    for m in media:
        m_urls = set()
        if args.title:
            for engine in args.title_prefix:
                suffix = m.get("title") or m["path"]
                m_urls.add(suffix if suffix.startswith("http") else web.construct_search(engine, suffix))

        if not args.title or args.path:
            if not m["path"].startswith("http"):
                for engine in args.title_prefix:
                    m_urls.add(web.construct_search(engine, m["path"]))
            else:
                m_urls.add(m["path"])

        pan.extend([{**m, "url": url} for url in m_urls if url not in urls])
        urls |= m_urls

    return pan


def open_links() -> None:
    args = parse_args()
    history.create(args)

    query, bindings = construct_links_query(args)
    media = list(args.db.query(query, bindings))

    if args.related >= consts.RELATED:
        media = db_media.get_related_media(args, media[0])

    if args.cluster_sort:
        from xklb.scripts.cluster_sort import cluster_dicts

        media = cluster_dicts(args, media)[: args.limit]

    media = make_souffle(args, media)

    if args.print:
        media_printer.media_printer(args, media)
        return

    if not media:
        processes.no_media_found()

    for m in media:
        play(args, m["path"], m["url"])

        sleep(0.1)
        if len(media) >= consts.MANY_LINKS:
            sleep(0.7)
