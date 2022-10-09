import argparse
import datetime as dt
import typing
from functools import partial
from itertools import takewhile
from pathlib import Path
from typing import Any, Dict, Optional

import praw, prawcore

from xklb import consts, db, utils
from xklb.consts import DBType
from xklb.utils import log

PRAW_SETUP_INSTRUCTIONS = r"""
You will need your Reddit user login info, client id, and secret.
See https://www.reddit.com/wiki/api for client id / secret.

Then create a praw.ini file:

[DEFAULT]
check_for_updates=False
[bot1]
client_id=
client_secret=
username=
password=
user_agent="test_script by u/YOUR_USERNAME_HERE"

And save it in the following location:

- Linux or Mac OS: ~/.config/praw.ini
- Windows: %APPDATA%\praw.ini

More details: https://praw.readthedocs.io/en/stable/getting_started/configuration/prawini.html
"""


"""
Catherine Devlin's reddit-to-sqlite project was very helpful in understanding
how to work with praw. Any lines of code which can be attributed to that person
should be.

https://github.com/catherinedevlin/reddit-to-sqlite

MIT License

Copyright (c) 2021 Catherine Devlin, Jacob Chapman

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def created_since(row: Any, target_sec_utc: Optional[int]) -> bool:
    result = (not target_sec_utc) or (row.created_utc >= target_sec_utc)
    return result


def legalize(val: Any) -> Any:
    if isinstance(val, praw.models.reddit.base.RedditBase):  # type: ignore
        return str(val)
    if isinstance(val, praw.models.reddit.poll.PollData):  # type: ignore
        d = val.__dict__
        d.pop("_reddit", None)
        return d
    return val


def _parent_ids_interpreted(dct: typing.Dict[str, typing.Any]) -> Dict[str, typing.Any]:
    if not dct.get("parent_id"):
        return dct

    prefix = dct["parent_id"][:3]
    dct["parent_clean_id"] = dct["parent_id"][3:]
    if prefix == "t1_":
        dct["parent_comment_id"] = dct["parent_clean_id"]
    elif prefix == "t3_":
        dct["parent_post_id"] = dct["parent_clean_id"]
    return dct


def saveable(item: Any) -> Dict[str, typing.Any]:
    result = {k: legalize(v) for k, v in item.__dict__.items() if not k.startswith("_")}
    return _parent_ids_interpreted(result)


def redditor_save_comments(args, user, user_name):
    latest_post_utc = args.db.pop(f"select max(time_created) from reddit_comments where author = ?", [user_name])
    get_since = dt.datetime.fromtimestamp(latest_post_utc or consts.NOW) - dt.timedelta(days=args.lookback)
    get_since = int(get_since.timestamp())
    log.info("Getting comments by %s since timestamp %s", user_name, get_since)
    _takewhile = partial(created_since, target_sec_utc=get_since)

    args.db["reddit_comments"].upsert_all(
        utils.list_dict_filter_bool(
            list(saveable(s) for s in takewhile(_takewhile, user.comments.new(limit=args.limit)))
        ),
        pk="id",
        alter=True,
    )


def slim_post_data(d: dict, playlist_path) -> dict:
    skip_domains = ["linktr.ee", "twitter.com", "t.me", "patreon", "onlyfans", "fans.ly", "file-upload", "file-link"]
    overridden_url = (
        d.get("url_overridden_by_dest") if any([domain in d["url"].lower() for domain in skip_domains]) else d["url"]
    )
    return {
        "path": overridden_url or d.get("url"),
        "id": d["id"],
        "archived": d.get("archived"),
        "author": d.get("author"),
        "author_flair_text": d.get("author_flair_text"),
        "author_is_blocked": d.get("author_is_blocked"),
        "time_created": d.get("created_utc"),
        "time_modified": d.get("edited"),
        "is_original_content": d.get("is_original_content"),
        "is_reddit_media_domain": d.get("is_reddit_media_domain"),
        "is_self": d.get("is_self"),
        "is_video": d.get("is_video"),
        "link_flair_text": d.get("link_flair_text"),
        "num_comments": d.get("num_comments"),
        "num_crossposts": d.get("num_crossposts"),
        "over_18": d.get("over_18"),
        "score": d.get("score"),
        "upvote_ratio": d.get("upvote_ratio"),
        "selftext_html": d.get("selftext_html"),
        "subreddit": d.get("subreddit"),
        "title": d.get("title"),
        "total_awards_received": d.get("total_awards_received"),
        "playlist_path": playlist_path,
    }


def redditor_new(args, redditor_dict) -> None:
    user_path, user_name = redditor_dict.values()
    user: praw.reddit.Redditor = args.reddit.redditor(user_name)

    latest_post_utc = args.db.pop(f"select max(time_created) from reddit_posts where author = ?", [user_name])
    get_since = dt.datetime.fromtimestamp(latest_post_utc or consts.NOW) - dt.timedelta(days=args.lookback)
    get_since = int(get_since.timestamp())
    log.info("Getting posts by %s since timestamp %s", user_name, get_since)
    _takewhile = partial(created_since, target_sec_utc=get_since)

    if args.comments:
        for s in takewhile(_takewhile, user.submissions.new(limit=args.limit)):
            s.time_created = s.created_utc
            args.db["reddit_posts"].upsert(utils.dict_filter_bool(saveable(s)), pk="path", alter=True)

        redditor_save_comments(args, user, user_name)
    else:
        for s in takewhile(_takewhile, user.submissions.new(limit=args.limit)):
            s.time_created = s.created_utc
            post_dict = utils.dict_filter_bool(saveable(s))
            if post_dict:
                post_dict = slim_post_data(post_dict, user_path)
                args.db["reddit_posts"].upsert(post_dict, pk="path", alter=True)


def enrich_subreddit_record(args, subreddit_name, post_dict):
    path = args.db.pop('select path from playlists where id = ? and ie_key = "reddit_praw_subreddit"', [subreddit_name])

    return args.db["playlists"].upsert(
        utils.dict_filter_bool(
            {
                "path": path,
                "subscribers": post_dict.pop("subreddit_subscribers", None),
                "visibility": post_dict.pop("subreddit_type", None),
            }
        ),
        pk="path",
        alter=True,
    )


def subreddit_save_comments(args, post, post_dict):
    post_dict["time_created"] = post_dict["created_utc"]
    args.db["reddit_posts"].upsert(post_dict, pk="path", alter=True)
    post.comments.replace_more()
    args.db["reddit_comments"].upsert_all(
        utils.list_dict_filter_bool(list(saveable(c) for c in post.comments.list())), pk="id", alter=True
    )


def subreddit_new(args, subreddit_dict) -> None:
    subreddit_path, subreddit_name = subreddit_dict.values()
    subreddit: praw.reddit.Subreddit = args.reddit.subreddit(subreddit_name)

    latest_post_utc = args.db.pop(f"select max(time_created) from reddit_posts where subreddit = ?", [subreddit_name])
    get_since = dt.datetime.fromtimestamp(latest_post_utc or consts.NOW) - dt.timedelta(days=args.lookback)
    get_since = int(get_since.timestamp())
    log.info("Getting posts in %s since timestamp %s", subreddit_name, get_since)

    _takewhile = partial(created_since, target_sec_utc=get_since)
    for idx, post in enumerate(takewhile(_takewhile, subreddit.new(limit=args.limit))):
        post_dict = utils.dict_filter_bool(saveable(post))
        if post_dict is None:
            continue

        if idx == 0:
            enrich_subreddit_record(args, subreddit_name, post_dict)

        if args.comments:
            subreddit_save_comments(args, post, post_dict)
        else:
            post_dict = slim_post_data(post_dict, subreddit_path)

            already_downloaded_path = args.db.pop(
                "SELECT path FROM media WHERE webpath =?",
                [post_dict["path"]],
                ignore_errors=["no such column", "no such table"],
            )
            if already_downloaded_path:
                post_dict["path"] = already_downloaded_path

            if post_dict["author_is_blocked"] == 1:
                continue
            elif post_dict["selftext_html"]:
                args.db["reddit_posts"].upsert(post_dict, pk="id", alter=True)
            else:
                args.db["media"].upsert(post_dict, pk="path", alter=True)


def subreddit_top(args, subreddit_dict) -> None:
    subreddit_path, subreddit_name = subreddit_dict.values()

    subreddit: praw.reddit.Subreddit = args.reddit.subreddit(subreddit_name)

    time_filters = ["all", "year", "month", "week", "day", "hour"]
    if args.lookback in [1, 2]:
        time_filters.reverse()
    time_filters = time_filters[: args.lookback]

    for time_filter in time_filters:
        log.info("Getting top posts in %s for time_filter '%s'", subreddit, time_filter)
        for post in subreddit.top(time_filter, limit=args.limit):
            post_dict = utils.dict_filter_bool(saveable(post))
            if post_dict is None:
                continue

            if args.comments:
                subreddit_save_comments(args, post, post_dict)
            else:
                post_dict = slim_post_data(post_dict, subreddit_path)

                already_downloaded_path = args.db.pop(
                    "SELECT path FROM media WHERE webpath =?",
                    [post_dict["path"]],
                    ignore_errors=["no such column", "no such table"],
                )
                if already_downloaded_path:
                    post_dict["path"] = already_downloaded_path

                if post_dict["author_is_blocked"] == 1:
                    continue
                elif post_dict["selftext_html"]:
                    args.db["reddit_posts"].upsert(post_dict, pk="id", alter=True)
                else:
                    args.db["media"].upsert(post_dict, pk="path", alter=True)


def parse_args(prog, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog, usage)
    parser.add_argument("--limit", default=1000)
    parser.add_argument("--lookback", default=4, type=int, help="Number of days to look back")
    parser.add_argument("--praw-site", default="bot1")

    parser.add_argument("--comments", action="store_true")
    parser.add_argument("--subreddits", action="store_true")
    parser.add_argument("--redditors", action="store_true")

    subp_profile = parser.add_mutually_exclusive_group()
    subp_profile.add_argument(
        "--audio", "-A", action="store_const", dest="profile", const=DBType.audio, help="Use audio downloader"
    )
    subp_profile.add_argument(
        "--video", "-V", action="store_const", dest="profile", const=DBType.video, help="Use video downloader"
    )
    subp_profile.add_argument(
        "--image", "-I", action="store_const", dest="profile", const=DBType.image, help="Use image downloader"
    )
    subp_profile.set_defaults(profile=DBType.video)

    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)

    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="reddit.db")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)
    args.paths = utils.conform(args.paths)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def reddit_add() -> None:
    args = parse_args(
        prog="library redditadd",
        usage="""library redditadd [--lookback N_DAYS] [--praw-site bot1] [database] paths ...

    Fetch data for redditors and reddits:

        library redditadd https://old.reddit.com/r/coolgithubprojects/ https://old.reddit.com/user/Diastro

    If you have a file with a list of subreddits you can do this:

        library redditadd --subreddits --db 96_Weird_History.db (cat ~/mc/96_Weird_History-reddit.txt)

    Likewise for redditors:

        library redditadd --redditors --db idk.db (cat ~/mc/shadow_banned.txt)
    """,
    )

    try:
        args.reddit = praw.Reddit(args.praw_site, config_interpolation="basic")
    except Exception as e:
        print(PRAW_SETUP_INSTRUCTIONS)
        raise SystemExit(e)

    subreddits = []
    redditors = []
    for path in args.paths:
        subreddit_matches = consts.REGEX_SUBREDDIT.match(path)
        redditor_matches = consts.REGEX_REDDITOR.match(path)
        ie_key = "reddit_praw"
        match = path
        if subreddit_matches:
            ie_key = "reddit_praw_subreddit"
            match = utils.conform(subreddit_matches.groups()).pop()
            subreddits.append({"path": path, "name": match})
        elif redditor_matches:
            ie_key = "reddit_praw_redditor"
            match = utils.conform(redditor_matches.groups()).pop()
            redditors.append({"path": path, "name": match})
        else:
            if args.subreddits:
                ie_key = "reddit_praw_subreddit"
                subreddits.append({"path": "https://old.reddit.com/r/" + path, "name": path})
            elif args.redditors:
                ie_key = "reddit_praw_redditor"
                redditors.append({"path": "https://old.reddit.com/user/" + path, "name": path})
            else:
                log.error(f"[{path}]: Skipping unknown URL")
                continue

        args.db["playlists"].upsert(
            utils.dict_filter_bool(
                {
                    "path": path,
                    "id": match,
                    "config": utils.get_config_opts(args, ["limit", "lookback", "praw_site", "comments"]),
                    "category": args.category,
                    "profile": args.profile,
                    "ie_key": ie_key,
                    "time_deleted": 0,
                }
            ),
            pk="path",
            alter=True,
        )

    skip_errors = (prawcore.exceptions.NotFound, prawcore.exceptions.Forbidden, prawcore.exceptions.Redirect)

    for subreddit in subreddits:
        try:
            subreddit_new(args, subreddit)
            subreddit_top(args, subreddit)
        except skip_errors as e:
            log.error("[%s] skipping subreddit: %s", subreddit["name"], e)
            continue

    for redditor in redditors:
        try:
            redditor_new(args, redditor)
        except skip_errors as e:
            log.error("[%s] skipping redditor: %s", redditor["name"], e)
            continue


if __name__ == "__main__":
    reddit_add()
