import argparse
import datetime as dt
import json
import sys
from functools import partial
from itertools import takewhile
from pathlib import Path
from typing import Any, Dict, Optional

import praw, prawcore

from xklb import consts, db, utils
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


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library " + action, usage=usage)
    parser.add_argument("--limit", default=1000, type=int)
    parser.add_argument("--lookback", default=4, type=int, help="Number of days to look back")
    parser.add_argument("--praw-site", default="bot1")

    parser.add_argument("--subreddits", action="store_true")
    parser.add_argument("--redditors", action="store_true")

    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)

    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    if action == "redditadd":
        parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if action == "redditadd":
        args.paths = utils.conform(args.paths)

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)

    try:
        args.reddit = praw.Reddit(args.praw_site, config_interpolation="basic")
    except Exception as e:
        print(PRAW_SETUP_INSTRUCTIONS)
        raise SystemExit(e)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


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

skip_errors = (prawcore.exceptions.NotFound, prawcore.exceptions.Forbidden, prawcore.exceptions.Redirect)


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


def _parent_ids_interpreted(dct: Dict[str, Any]) -> Dict[str, Any]:
    if not dct.get("parent_id"):
        return dct

    prefix = dct["parent_id"][:3]
    dct["parent_clean_id"] = dct["parent_id"][3:]
    if prefix == "t1_":
        dct["parent_comment_id"] = dct["parent_clean_id"]
    elif prefix == "t3_":
        dct["parent_post_id"] = dct["parent_clean_id"]
    return dct


def saveable(item: Any) -> Dict[str, Any]:
    result = {k: legalize(v) for k, v in item.__dict__.items() if not k.startswith("_")}
    return _parent_ids_interpreted(result)


def slim_post_data(d: dict, playlist_path=None) -> dict:
    skip_domains = ["linktr.ee", "twitter.com", "t.me", "patreon", "onlyfans", "fans.ly", "file-upload", "file-link"]
    url = d.get("url")
    if url:
        url = url.lower()
    if not url or any([domain in url for domain in skip_domains]):
        d["url"] = d.get("url_overridden_by_dest")

    selftext = d.get("selftext")
    if selftext and selftext in (
        "[deleted]",
        "[removed]",
        "[ Removed by reddit in response to a copyright notice. ]",
        "[ Removed by reddit on account of violating the [content policy](/help/contentpolicy). ]",
    ):
        selftext = None

    return {
        "path": url,
        "author": d.get("author"),
        "author_flair_text": d.get("author_flair_text"),
        "time_created": d.get("created_utc"),
        "time_modified": int(d.get("edited") or 0),
        "is_over_18": d.get("over_18"),
        "is_crosspostable": d.get("is_crosspostable"),
        "is_original_content": d.get("is_original_content"),
        "is_video": d.get("is_video"),
        "link_flair_text": d.get("link_flair_text"),
        "num_comments": d.get("num_comments"),
        "num_crossposts": d.get("num_crossposts"),
        "score": d.get("score"),
        "upvote_ratio": d.get("upvote_ratio"),
        "selftext": selftext,
        "title": d.get("title"),
        "total_awards_received": d.get("total_awards_received"),
        "playlist_path": playlist_path,
    }


def save_post(args, post_dict, subreddit_path):
    slim_dict = utils.dict_filter_bool(slim_post_data(post_dict, subreddit_path))

    if slim_dict:
        already_downloaded_path = args.db.pop(
            "SELECT path FROM media WHERE webpath =?",
            [slim_dict["path"]],
            ignore_errors=["no such column", "no such table"],
        )
        if already_downloaded_path:
            slim_dict["path"] = already_downloaded_path

        existing_meta = args.db.pop_dict(
            "SELECT play_count, time_played, time_downloaded, time_deleted FROM media WHERE path =?",
            [slim_dict["path"]],
            ignore_errors=["no such column", "no such table"],
        )
        slim_dict = {
            **slim_dict,
            "play_count": 0,
            "time_played": 0,
            "time_downloaded": 0,
            "time_deleted": 0,
            **(existing_meta or {}),
        }

        if post_dict.get("author_is_blocked") == 1:
            pass
        elif "selftext" in slim_dict:
            args.db["reddit_posts"].upsert(slim_dict, pk=["path", "playlist_path"], alter=True)
        else:
            args.db["media"].upsert(slim_dict, pk=["path", "playlist_path"], alter=True)


def since_last_created(args, playlist_path):
    latest_post_utc = args.db.pop(
        f"""
        select max(time_created)
        from (
            select time_created, playlist_path from reddit_posts
            UNION ALL
            select time_created, playlist_path from media
        )
        where playlist_path = ?
    """,
        [playlist_path],
        ignore_errors=["no such column", "no such table"],
    )
    if latest_post_utc:
        get_since = dt.datetime.fromtimestamp(latest_post_utc) - dt.timedelta(days=args.lookback)
        get_since = int(get_since.timestamp())
        log.info("Getting posts since timestamp %s", get_since)
    else:
        get_since = 0
        log.info("Getting posts since the dawn of time...")

    _takewhile = partial(created_since, target_sec_utc=get_since)
    return _takewhile


def redditor_new(args, redditor_dict) -> None:
    user_path, user_name = redditor_dict.values()
    user: praw.reddit.Redditor = args.reddit.redditor(user_name)

    _takewhile = since_last_created(args, user_path)
    log.info("Getting new posts")

    for s in takewhile(_takewhile, user.submissions.new(limit=args.limit)):
        s.time_created = s.created_utc
        save_post(args, saveable(s), user_path)


def subreddit_new(args, subreddit_dict) -> None:
    subreddit_path, subreddit_name = subreddit_dict.values()
    subreddit: praw.reddit.Subreddit = args.reddit.subreddit(subreddit_name)

    _takewhile = since_last_created(args, subreddit_path)
    log.info("Getting new posts")
    for idx, post in enumerate(takewhile(_takewhile, subreddit.new(limit=args.limit))):
        post_dict = saveable(post)

        if idx == 0:
            args.db["playlists"].upsert(
                utils.dict_filter_bool(
                    {
                        "path": subreddit_path,
                        "subscribers": post_dict.pop("subreddit_subscribers", None),
                        "visibility": post_dict.pop("subreddit_type", None),
                    }
                ),
                pk="path",
                alter=True,
            )

        save_post(args, post_dict, subreddit_path)


def subreddit_top(args, subreddit_dict) -> None:
    subreddit_path, subreddit_name = subreddit_dict.values()

    subreddit: praw.reddit.Subreddit = args.reddit.subreddit(subreddit_name)

    time_filters = ["all", "year", "month", "week", "day", "hour"]
    if args.lookback in [1, 2]:
        time_filters.reverse()
    time_filters = time_filters[: args.lookback]

    _takewhile = since_last_created(args, subreddit_path)
    for time_filter in time_filters:
        log.info("Getting top posts in %s for time_filter '%s'", subreddit, time_filter)
        for post in takewhile(_takewhile, subreddit.top(time_filter, limit=args.limit)):
            save_post(args, saveable(post), subreddit_path)


def process_redditors(args, redditors):
    for redditor in redditors:
        try:
            redditor_new(args, redditor)
        except skip_errors as e:
            log.error("[%s] skipping redditor: %s", redditor["name"], e)
            continue


def process_subreddits(args, subreddits):
    for subreddit in subreddits:
        try:
            subreddit_new(args, subreddit)
            subreddit_top(args, subreddit)
        except skip_errors as e:
            log.error("[%s] skipping subreddit: %s", subreddit["name"], e)
            continue


def reddit_add(args=None) -> None:
    if args:
        sys.argv = ["lb"] + args

    args = parse_args(
        "redditadd",
        usage="""library redditadd [--lookback N_DAYS] [--praw-site bot1] [database] paths ...

    Fetch data for redditors and reddits:

        library redditadd https://old.reddit.com/r/coolgithubprojects/ https://old.reddit.com/user/Diastro

    If you have a file with a list of subreddits you can do this:

        library redditadd --subreddits --db 96_Weird_History.db (cat ~/mc/96_Weird_History-reddit.txt)

    Likewise for redditors:

        library redditadd --redditors --db idk.db (cat ~/mc/shadow_banned.txt)
    """,
    )

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
                path = f"https://old.reddit.com/r/{match}/"
                subreddits.append({"path": path, "name": match})
            elif args.redditors:
                ie_key = "reddit_praw_redditor"
                path = f"https://old.reddit.com/user/{match}/"
                redditors.append({"path": path, "name": match})
            else:
                log.error(f"[{path}]: Skipping unknown URL")
                continue

        args.db["playlists"].upsert(
            utils.dict_filter_bool(
                {
                    "path": path,
                    "id": match,
                    "config": utils.filter_namespace(args, ["limit", "lookback", "praw_site"]),
                    "category": args.category or ie_key,
                    "ie_key": ie_key,
                    "time_deleted": 0,
                }
            ),
            pk="path",
            alter=True,
        )

    process_subreddits(args, subreddits)
    process_redditors(args, redditors)
    if not args.db["media"].detect_fts() or len(subreddits + redditors) > 75:
        db.optimize(args)


def reddit_update(args=None) -> None:
    if args:
        sys.argv = ["lb"] + args

    args = parse_args(
        "redditupdate",
        usage="""library redditupdate [--audio | --video] [-c CATEGORY] [--lookback N_DAYS] [--praw-site bot1] [database]

    Fetch the latest posts for every subreddit/redditor saved in your database

        library redditupdate edu_subreddits.db
    """,
    )
    playlists = db.get_playlists(
        args,
        "ie_key, path, id, config",
        sql_filters=['AND ie_key in ("reddit_praw_subreddit","reddit_praw_redditor")'],
        constrain=True,
    )

    for playlist in playlists:
        config = json.loads(playlist["config"])
        args_env = args if not config else argparse.Namespace(**{**config, **args.__dict__})

        if playlist["ie_key"] == "reddit_praw_subreddit":
            process_subreddits(args_env, [{"path": playlist["path"], "name": playlist["id"]}])
        elif playlist["ie_key"] == "reddit_praw_subreddit":
            process_redditors(args_env, [{"path": playlist["path"], "name": playlist["id"]}])
