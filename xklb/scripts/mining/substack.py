import argparse
from pathlib import Path

from bs4 import BeautifulSoup

from xklb import db, media, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library substack", usage=usage.substack)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--cookies")
    parser.add_argument("--cookies-from-browser")

    parser.add_argument("database")
    parser.add_argument("paths", nargs="+", help="Substack path to extract article for")
    args = parser.parse_args()

    Path(args.database).touch()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def save_page(args, url):
    text = utils.requests_authed_get(args, url)
    soup = BeautifulSoup(text, "html.parser")
    utils.download_embeds(args, soup)

    try:
        subtitle = soup.select_one("h3.subtitle").getText()
    except AttributeError:
        subtitle = None

    article = {
        "path": url,
        "time_created": utils.to_timestamp(utils.find_date(soup)),
        "author": soup.find("meta", {"name": "author"})["content"],
        "title": soup.select_one("h1.post-title").getText(),
        "subtitle": subtitle,
        "text": soup.select_one("div.body").prettify(),
    }

    media.add(args, article)


def substack():
    args = parse_args()
    for path in args.paths:
        save_page(args, path)


if __name__ == "__main__":
    substack()
