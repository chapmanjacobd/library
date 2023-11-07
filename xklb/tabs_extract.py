import argparse, sys
from pathlib import Path
from typing import List

from xklb import db_media, history, usage
from xklb.utils import consts, db_utils, iterables, objects, path_utils, strings
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library tabsadd", usage=usage.tabsadd)
    parser.add_argument(
        "--frequency",
        "--freqency",
        "-f",
        metavar="frequency",
        default="monthly",
        const="monthly",
        type=str.lower,
        nargs="?",
        help=f"One of: {', '.join(consts.frequency)} (default: %(default)s)",
    )
    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)
    parser.add_argument("--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters")
    parser.add_argument("--allow-immediate", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    args.frequency = strings.partial_startswith(args.frequency, consts.frequency)

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def get_new_paths(args) -> List[str]:
    if not args.no_sanitize:
        args.paths = [path_utils.sanitize_url(args, path) for path in args.paths]

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
    except Exception as e:
        log.debug(e)
    else:
        if existing:
            print(f"Updating frequency for {len(existing)} existing paths")
            db_media.mark_media_deleted(args, list(existing))

    args.paths = iterables.conform([path.strip() for path in args.paths])
    return args.paths


def extract_url_metadata(args, path: str) -> dict:
    from urllib.parse import urlparse

    hostname = urlparse(path).hostname or ""

    return {
        "path": path,
        "hostname": hostname,
        "frequency": args.frequency,
        "category": args.category or "Uncategorized",
        "time_created": consts.APPLICATION_START,
        "time_deleted": 0,
    }


def tabs_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]
    args = parse_args()

    tabs = iterables.list_dict_filter_bool([extract_url_metadata(args, path) for path in get_new_paths(args)])
    for tab in tabs:
        db_media.add(args, tab)
    if not args.allow_immediate:
        history.add(args, [d["path"] for d in tabs], mark_done=True)  # prevent immediately opening
