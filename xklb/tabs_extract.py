import argparse, sys
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from xklb import db, player, utils
from xklb.consts import Frequency
from xklb.utils import argparse_enum, log, sanitize_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library tabsadd",
        usage=r"""library tabsadd --frequency {daily,weekly,monthly,quarterly,yearly} --category CATEGORY [--no-sanitize] [database] paths ...

    Adding one URL:

        library tabsadd -f monthly -c travel ~/lb/tabs.db https://old.reddit.com/r/Colombia/top/?sort=top&t=month

        Depending on your shell you may need to escape the URL (add quotes)

        If you use Fish shell know that you can enable features to make pasting easier:
            set -U fish_features stderr-nocaret qmark-noglob regex-easyesc ampersand-nobg-in-token

        Also I recommend turning Ctrl+Backspace into a super-backspace for repeating similar commands with long args:
            echo 'bind \b backward-kill-bigword' >> ~/.config/fish/config.fish

    Importing from a line-delimitated file:

        library tabsadd -f yearly -c reddit ~/lb/tabs.db (cat ~/mc/yearly-subreddit.cron)

""",
    )
    parser.add_argument(
        "--frequency",
        "--freqency",
        "-f",
        default=Frequency.Monthly,
        type=Frequency,
        action=argparse_enum,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)
    parser.add_argument("--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="tabs.db")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def get_new_paths(args) -> List[str]:
    if not args.no_sanitize:
        args.paths = [sanitize_url(args, path) for path in args.paths]

    if args.category is None:
        qb = (
            "select path from media where path in (" + ",".join(["?"] * len(args.paths)) + ")",
            (*args.paths,),
        )
    else:
        qb = (
            "select path from media where category = ? and path in (" + ",".join(["?"] * len(args.paths)) + ")",
            (args.category, *args.paths),
        )

    try:
        existing = {d["path"] for d in args.db.query(*qb)}
    except Exception:
        pass
    else:
        if existing:
            print(f"Updating frequency for {len(existing)} existing paths")
            player.mark_media_deleted(args, list(existing))

    args.paths = utils.conform([path.strip() for path in args.paths])
    return args.paths


def extract_url_metadata(args, path: str) -> dict:
    hostname = urlparse(path).hostname or ""

    return dict(
        path=path,
        hostname=hostname,
        frequency=args.frequency.value,
        category=args.category or "Uncategorized",
        time_created=int(datetime.now().timestamp()),
        time_played=0,
        play_count=0,
        time_deleted=0,
    )


def tabs_add(args=None) -> None:
    if args:
        sys.argv[1:] = args
    args = parse_args()

    tabs = [extract_url_metadata(args, path) for path in get_new_paths(args)]
    args.db["media"].insert_all(utils.list_dict_filter_bool(tabs), pk="path", alter=True, replace=True)
