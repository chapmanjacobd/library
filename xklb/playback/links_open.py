import argparse, shlex, webbrowser
from pathlib import Path
from time import sleep

from xklb import media_printer, usage
from xklb.mediadb import db_history, db_media
from xklb.utils import arg_utils, arggroups, consts, db_utils, iterables, objects, processes, web
from xklb.utils.log_utils import log
from xklb.utils.printing import pipe_print


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library open-links",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        usage=usage.links_open,
    )
    arggroups.sql_fs(parser)

    parser.add_argument("--path", action="store_true")
    parser.add_argument("--title", action="store_true")
    parser.add_argument("--title-prefix", "--prefix", nargs="+", action="extend")

    parser.add_argument("--online-media-only", "--online", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local-media-only", "--local", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--category", "-c")

    arggroups.operation_cluster(parser)
    arggroups.operation_related(parser)

    parser.add_argument("--browser")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = consts.SC.links_open
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

    if args.sort:
        args.sort = [arg_utils.override_sort(s) for s in args.sort]
        args.sort = " ".join(args.sort)

    if args.cols:
        args.cols = list(iterables.flatten([s.split(",") for s in args.cols]))

    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def construct_links_query(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")

    args.filter_sql = []
    args.filter_bindings = {}

    args.filter_sql.extend([" and " + w for w in args.where])

    for idx, inc in enumerate(args.include):
        args.filter_sql.append(
            f"""and (
                path like :include{idx}
                {f'OR title like :include{idx}' if 'title' in m_columns else ''}
            )"""
        )
        if args.exact:
            args.filter_bindings[f"include{idx}"] = inc
        else:
            args.filter_bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        args.filter_sql.append(
            f"""and (
                path not like :exclude{idx}
                {f'AND title not like :exclude{idx}' if 'title' in m_columns else ''}
            )"""
        )
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
    offset_sql = f"OFFSET {args.offset}" if args.offset and limit_sql else ""

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
        if "".join(args.browser) in ["echo", "print"]:
            pipe_print(url)
        else:
            processes.cmd(*args.browser, url)
    else:
        webbrowser.open(url, 2, autoraise=False)
    db_history.add(args, [path], time_played=consts.APPLICATION_START, mark_done=True)


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


def links_open() -> None:
    args = parse_args()
    db_history.create(args)

    query, bindings = construct_links_query(args)
    media = list(args.db.query(query, bindings))

    if args.related >= consts.RELATED:
        media = db_media.get_related_media(args, media[0])

    if args.cluster_sort:
        from xklb.text.cluster_sort import cluster_dicts

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
