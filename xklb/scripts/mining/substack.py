import argparse
from pathlib import Path

from bs4 import BeautifulSoup

from xklb import db_media, usage
from xklb.utils import db_utils, nums, objects, web
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library substack", usage=usage.substack)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--cookies")
    parser.add_argument("--cookies-from-browser")

    parser.add_argument("database")
    parser.add_argument("paths", nargs="+", help="Substack path to extract article for")
    args = parser.parse_args()

    Path(args.database).touch()
    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def save_page(args, url):
    text = web.requests_authed_get(args, url)
    soup = BeautifulSoup(text, "html.parser")
    web.download_embeds(args, soup)

    try:
        subtitle = soup.select_one("h3.subtitle").getText()  # type: ignore
    except AttributeError:
        subtitle = None

    article = {
        "path": url,
        "time_created": nums.to_timestamp(web.find_date(soup)),
        "author": soup.find("meta", {"name": "author"})["content"],  # type: ignore
        "title": soup.select_one("h1.post-title").getText(),  # type: ignore
        "subtitle": subtitle,
        "text": soup.select_one("div.body").prettify(),  # type: ignore
    }

    db_media.add(args, article)


def substack():
    args = parse_args()
    for path in args.paths:
        save_page(args, path)


if __name__ == "__main__":
    substack()
