import argparse, html
from urllib.parse import urlparse

from library import usage
from library.mediadb import db_media
from library.utils import arggroups, argparse_utils, db_utils, log_utils
from library.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.reddit_selftext)
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    return args


def get_page_links(path, text) -> tuple[set, set]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html.unescape(text), "lxml")
    internal_links = set()
    external_links = set()

    for a in soup.findAll("a", attrs={"href": True}):
        href = a["href"].strip()
        if all([len(href) > 1, href[0] != "#", "javascript:" not in href, "mailto:" not in href, "tel:" not in href]):
            if "http" in href or "https" in href:
                if urlparse(path).netloc.lower() in urlparse(href).netloc.lower():
                    internal_links.add(a["href"])
                else:
                    external_links.add(a["href"])
            else:
                log_utils.log.debug(a["href"])

    return internal_links, external_links


def reddit_selftext() -> None:
    from markdown_it import MarkdownIt

    args = parse_args()
    m_columns = db_utils.columns(args, "media")

    reddit_posts = list(
        args.db.query(
            f"""
            select path, selftext
            from reddit_posts
            where 1=1
                {'AND path not in (select distinct webpage from media where webpage is not null)' if 'webpage' in m_columns else ''}
            """,
        ),
    )

    md = MarkdownIt()

    for d in reddit_posts:
        html_data = md.render(d["selftext"])
        internal_links, external_links = get_page_links(d["path"], html_data)
        if internal_links:
            for i_link in internal_links:
                log.info(i_link)

        for e_link in external_links:
            db_media.add(args, {**d, "path": e_link, "webpage": d["path"]})
