import argparse
import datetime as dt
import typing
from functools import partial
from itertools import takewhile
from pathlib import Path
from typing import Any, Dict, List, Optional

import praw

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


"""
Catherine Devlin's reddit-to-sqlite project was very helpful in understanding
how to work with praw. Any lines of code which can be attributed to that person
should be and they fall into the MIT license from the year 2021.

https://github.com/catherinedevlin/reddit-to-sqlite

MIT License

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


def user_new(args, username: str) -> None:
    user = args.reddit.redditor(username)

    latest_post_utc = args.db.pop(f"select max(created_utc) from reddit_posts where author = '{username}'")
    get_since = dt.datetime.fromtimestamp(latest_post_utc or consts.NOW) - dt.timedelta(days=args.lookback)
    get_since = int(get_since.timestamp())
    log.info("Getting posts by %s since timestamp %s", username, get_since)
    _takewhile = partial(created_since, target_sec_utc=get_since)

    args.db["reddit_posts"].upsert_all(
        (saveable(s) for s in takewhile(_takewhile, user.submissions.new(limit=args.limit))), pk="id", alter=True
    )

    if args.comments:
        latest_post_utc = args.db.pop(f"select max(created_utc) from reddit_comments where author = '{username}'")
        get_since = dt.datetime.fromtimestamp(latest_post_utc or consts.NOW) - dt.timedelta(days=args.lookback)
        get_since = int(get_since.timestamp())
        log.info("Getting comments by %s since timestamp %s", username, get_since)
        _takewhile = partial(created_since, target_sec_utc=get_since)

        args.db["reddit_comments"].upsert_all(
            (saveable(s) for s in takewhile(_takewhile, user.comments.new(limit=args.limit))), pk="id", alter=True
        )


def subreddit_new(args, subreddit_name: str) -> None:
    subreddit = args.reddit.subreddit(subreddit_name)

    latest_post_utc = args.db.pop(f"select max(created_utc) from reddit_posts where subreddit = '{subreddit}'")
    get_since = dt.datetime.fromtimestamp(latest_post_utc or consts.NOW) - dt.timedelta(days=args.lookback)
    get_since = int(get_since.timestamp())
    log.info("Getting posts in %s since timestamp %s", subreddit, get_since)

    _takewhile = partial(created_since, target_sec_utc=get_since)
    for post in takewhile(_takewhile, subreddit.new(limit=args.limit)):
        log.debug("Post id %s", post.id)
        args.db["reddit_posts"].upsert(saveable(post), pk="id", alter=True)

        if args.comments:
            post.comments.replace_more()
            args.db["reddit_comments"].upsert_all((saveable(c) for c in post.comments.list()), pk="id", alter=True)


def subreddit_top(args, subreddit_name: str) -> None:
    subreddit = args.reddit.subreddit(subreddit_name)

    time_filters = ["all", "year", "month", "week", "day", "hour"]
    if args.lookback in [1, 2]:
        time_filters.reverse()
    time_filters = time_filters[: args.lookback]

    for time_filter in time_filters:
        log.info("Getting top posts in %s for time_filter '%s'", subreddit, time_filter)
        for post in subreddit.top(time_filter, limit=args.limit):
            log.debug("Post id %s", post.id)
            args.db["reddit_posts"].upsert(saveable(post), pk="id", alter=True)

            if args.comments:
                post.comments.replace_more()
                args.db["reddit_comments"].upsert_all((saveable(c) for c in post.comments.list()), pk="id", alter=True)


def parse_paths(args) -> Dict[str, List[str]]:
    paths: List[str] = args.paths
    path_groups = {}
    for path in paths:
        subreddit_matches = consts.REGEX_SUBREDDIT.match(path)
        user_matches = consts.REGEX_REDDITOR.match(path)
        if subreddit_matches:
            subreddit = subreddit_matches.groups()[0]
            path_groups.setdefault("subreddits", []).append(subreddit)
        elif user_matches:
            user = user_matches.groups()[0]
            path_groups.setdefault("users", []).append(user)
        else:
            if args.subreddits:
                path_groups.setdefault("subreddits", []).append(path)
            elif args.users:
                path_groups.setdefault("users", []).append(path)
            else:
                log.error(f"[{path}]: Skipping unknown URL")

    return path_groups


def parse_args(prog, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog, usage)
    parser.add_argument("--limit", default=1000)
    parser.add_argument("--lookback", default=4, type=int, help="Number of days to look back")
    parser.add_argument("--praw-site", default="bot1")

    parser.add_argument("--comments", action="store_true")
    parser.add_argument("--subreddits", action="store_true")
    parser.add_argument("--users", action="store_true")

    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="reddit.db")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)
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

    Likewise for users:

        library redditadd --users --db idk.db (cat ~/mc/shadow_banned.txt)
    """,
    )

    try:
        args.reddit = praw.Reddit(args.praw_site, config_interpolation="basic")
    except Exception as e:
        print(PRAW_SETUP_INSTRUCTIONS)
        raise e

    args.path_groups = parse_paths(args)
    for k, v_list in args.path_groups.items():
        for v in v_list:
            args.db[k].upsert(
                {
                    "id": v,
                    "config": utils.get_config_opts(args, ["limit", "lookback", "praw_site", "comments"]),
                },
                pk="id",
                alter=True,
            )

    subreddits = args.path_groups.pop("subreddits", [])
    for subreddit in subreddits:
        subreddit_new(args, subreddit)
        subreddit_top(args, subreddit)

    users = args.path_groups.pop("users", [])
    for user in users:
        user_new(args, user)


if __name__ == "__main__":
    reddit_add()
