import argparse, shlex, webbrowser
from time import sleep

from xklb import media_printer, usage
from xklb.mediadb import db_history, db_media
from xklb.utils import arggroups, argparse_utils, consts, processes, sqlgroups, web
from xklb.utils.printing import pipe_print


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(
        prog="library open-links",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        usage=usage.links_open,
    )
    arggroups.sql_fs(parser)

    parser.add_argument("--path", action="store_true")
    parser.add_argument("--title", action="store_true")
    parser.add_argument("--title-prefix", "--prefix", nargs="+", action="extend")

    parser.add_argument("--category", "-c")

    arggroups.cluster(parser)
    arggroups.related(parser)

    parser.add_argument("--browser")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = consts.SC.links_open
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)

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

    query, bindings = sqlgroups.construct_links_query(args)
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
