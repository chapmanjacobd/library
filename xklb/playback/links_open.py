import argparse, shlex, webbrowser
from time import sleep

from xklb import usage
from xklb.mediadb import db_history, db_media
from xklb.playback import media_printer
from xklb.utils import arggroups, argparse_utils, consts, processes, sqlgroups, web
from xklb.utils.printing import pipe_print


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.links_open)
    arggroups.sql_fs(parser)

    parser.add_argument("--path", action="store_true")
    parser.add_argument("--title", action="store_true")
    parser.add_argument("--title-prefix", "--prefix", nargs="+", action="extend")

    parser.add_argument("--category", "-c")

    arggroups.text_filtering(parser)
    arggroups.cluster_sort(parser)
    arggroups.regex_sort(parser)
    arggroups.related(parser)

    parser.add_argument("--browser")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*")

    parser.set_defaults(limit="7", fts=False)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    arggroups.regex_sort_post(args)

    if not args.title_prefix:
        args.title_prefix = ["https://www.google.com/search?q=%"]
    args.title_prefix = [s if "%" in s else s + "%" for s in args.title_prefix]

    if args.browser:
        args.browser = shlex.split(args.browser)

    return args


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

    is_whole_db_query = any(
        [
            args.cluster_sort,
            args.regex_sort,
            "a" in args.print,
        ]
    )

    query, bindings = sqlgroups.construct_links_query(args, limit=None if is_whole_db_query else args.limit)
    media = list(args.db.query(query, bindings))

    if args.related >= consts.RELATED:
        media = db_media.get_related_media(args, media[0])

    if args.regex_sort:
        from xklb.text import regex_sort

        media = regex_sort.sort_dicts(args, media)
    elif args.cluster_sort:
        from xklb.text import cluster_sort

        media = cluster_sort.sort_dicts(args, media)

    if not "a" in args.print:
        if is_whole_db_query:
            media = media[: args.limit]
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
