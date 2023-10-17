from xklb.utils.log_utils import log


def try_get_feed(path):
    import feedparser

    feed = feedparser.parse(path)
    if feed.version:
        return feed
    return None


def try_get_head_link(path):
    import requests
    from bs4 import BeautifulSoup

    try:
        response = requests.get(path)
        soup = BeautifulSoup(response.text, "html.parser")
        link = soup.find("link", type="application/rss+xml")
        if link:
            return link.get("href")  # type: ignore
    except TypeError:
        return None


def try_get_link_endswith(path):
    import requests
    from bs4 import BeautifulSoup

    try:
        response = requests.get(path)
        soup = BeautifulSoup(response.text, "html.parser")
        link = soup.find("a", href=lambda href: href and (href.endswith((".rss", ".xml"))))  # type: ignore
        if link:
            return link.get("href")  # type: ignore
    except TypeError:
        return None


def get_feed(path):
    feed = try_get_feed(path)
    if feed is None:
        head_path = try_get_head_link(path)
        feed = try_get_feed(head_path)

    if feed is None:
        endswith_path = try_get_link_endswith(path)
        feed = try_get_feed(endswith_path)

    return feed


def save(args, feed):
    entries = feed.entries
    raise


def process_path(args, path):
    feed = get_feed(path)
    if feed:
        save(args, feed)
    else:
        log.error("[%s]: No RSS feed found.")
