import argparse
from datetime import datetime, timezone
from pathlib import Path
from time import sleep

import requests
from bs4 import BeautifulSoup
from dateutil import parser

from xklb import db, media, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library tildes", usage=usage.tildes)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--cookies")
    parser.add_argument("--cookies-from-browser")

    parser.add_argument("database")
    parser.add_argument("username", help="Tildes.net user to extract comments for")
    args = parser.parse_args()

    if args.cookies or args.cookies_from_browser:
        args.authed_web = utils.ChocolateChip(args)

    Path(args.database).touch()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def save_page(args, url):
    if args.cookies or args.cookies_from_browser:
        text = args.authed_web.get(url)
    else:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        text = response.text

    soup = BeautifulSoup(text, "html.parser")

    comment_elements = soup.find_all("article", class_="comment")
    for comment_element in comment_elements:
        edited_time_element = comment_element.find("time", class_="comment-edited-time")
        score_element = comment_element.find("div", class_="comment-votes")
        parent_path_element = comment_element.find("a", class_="comment-nav-link", text="Parent")
        comment = {
            "path": "https://tildes.net" + comment_element.find("a", class_="comment-nav-link")["href"],
            "parent_path": "https://tildes.net" + parent_path_element["href"] if parent_path_element else None,
            "time_created": int(
                datetime.fromisoformat(
                    comment_element.find("time", class_="comment-posted-time")["datetime"][:-1],
                ).timestamp(),
            ),
            "time_modified": int(datetime.fromisoformat(edited_time_element["datetime"][:-1]).timestamp())
            if edited_time_element
            else None,
            "score": int(score_element.text.split()[0]) if score_element else 0,
            "text": "".join(str(el) for el in comment_element.find("div", class_="comment-text").contents),
        }
        media.add(args, comment)

    topic_elements = soup.find_all("article", class_="topic")
    for topic_element in topic_elements:
        topic_title_element = topic_element.find("h1", class_="topic-title")
        num_comments_element = topic_element.find("span", class_="topic-info-comments")
        score_element = topic_element.find("span", class_="topic-voting-votes")
        article_words_element = topic_element.find("span", string=lambda text: "words" in text)
        published_date_element = topic_element.find("span", string=lambda text: "published" in text)
        topic_group_element = topic_element.find("span", class_="topic-group")
        topic_source_element = topic_element.find("div", class_="topic-info-source")

        path = topic_title_element.a["href"]
        if path.startswith("/"):
            path = "https://tildes.net" + path

        text_element = topic_element.find("details", class_="topic-text-excerpt")
        if text_element:
            text_element = text_element.find("p")
        else:
            text_element = topic_element.find("p", class_="topic-text-excerpt")

        topic_group = None
        if topic_group_element and topic_group_element.a:
            topic_group = topic_group_element.a.get_text("\n", strip=True)
        elif topic_group_element:
            topic_group = topic_group_element.get_text("\n", strip=True)

        topic_source = None
        if topic_source_element and topic_source_element.a:
            topic_source = topic_source_element.a.get_text("\n", strip=True)
        elif topic_source_element:
            topic_source = topic_source_element.get_text("\n", strip=True)

        time_published = None
        if published_date_element:
            published_date = published_date_element.get_text("\n", strip=True).split()[-1]
            time_published = int(parser.parse(published_date).replace(tzinfo=timezone.utc).timestamp())

        num_words = None
        if article_words_element:
            num_words = int(article_words_element.get_text("\n", strip=True).split()[0])
        elif text_element:
            num_words = len(text_element.get_text().split())

        topic = {
            "path": path,
            "path_parent": topic_source,
            "topic_group": topic_group,
            "time_created": int(
                datetime.fromisoformat(
                    topic_element.find("time", class_="time-responsive")["datetime"][:-1],
                ).timestamp(),
            ),
            "time_published": time_published,
            "score": int(score_element.text.split()[0]) if score_element else 0,
            "num_comments": int(num_comments_element.span.get_text("\n", strip=True).split()[0])
            if num_comments_element
            else 0,
            "num_words": num_words,
            "title": topic_title_element.get_text("\n", strip=True),
            "text": "".join(str(el) for el in text_element.contents) if text_element else None,
        }
        media.add(args, topic)

    main_element = soup.find("main")
    if main_element:
        pagination = main_element.find("div", class_="pagination")
        if pagination:
            next_a = pagination.find("a", text="Next")
            if next_a:
                next_page_url = next_a["href"]
                sleep(1)
                save_page(args, next_page_url)


def tildes():
    args = parse_args()
    save_page(args, f"https://tildes.net/user/{args.username}")


if __name__ == "__main__":
    tildes()
