import argparse, sys
from datetime import datetime, timedelta
from pathlib import Path
from random import randint

from xklb import db_media, history, usage
from xklb.utils import arggroups, consts, db_utils, iterables, objects, path_utils, strings
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library tabsadd", usage=usage.tabsadd)
    arggroups.extractor(parser)
    arggroups.frequency(parser)

    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)
    parser.add_argument("--allow-immediate", action="store_true")
    arggroups.debug(parser)
    arggroups.database(parser)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_intermixed_args()

    args.frequency = strings.partial_startswith(args.frequency, consts.frequency)

    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def get_days(frequency):
    d = {"weekly": 7, "monthly": 30, "quarterly": 89, "yearly": 364, "decadally": 3640}
    return d.get(frequency, 7)


def get_new_paths(args) -> list[str]:
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
            with args.db.conn:  # type: ignore
                for p in list(existing):
                    args.db.conn.execute(  # type: ignore
                        "DELETE from history WHERE media_id = (select id from media where path = ?)", [p]
                    )
            db_media.mark_media_deleted(args, list(existing))

    args.paths = iterables.conform([path.strip() for path in args.paths])
    return args.paths


def consolidate_url(args, path: str) -> dict:
    from urllib.parse import urlparse

    hostname = urlparse(path).hostname or ""

    return {
        "path": path,
        "hostname": hostname,
        "frequency": getattr(args, "frequency", None),
        "category": getattr(args, "category", None) or "Uncategorized",
        "time_created": consts.APPLICATION_START,
        "time_deleted": 0,
    }


def tabs_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]
    args = parse_args()

    tabs = iterables.list_dict_filter_bool([consolidate_url(args, path) for path in get_new_paths(args)])
    for tab in tabs:
        db_media.add(args, tab)
    if not args.allow_immediate and args.frequency != "daily":
        # prevent immediately opening -- pick a random day within the week
        min_date = datetime.today() - timedelta(days=get_days(args.frequency) - 2)  # at least two days away
        max_date = datetime.today()

        min_time = int(min_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        max_time = int(max_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

        for d in tabs:
            time_played = randint(min_time, max_time)
            history.add(args, [d["path"]], time_played=time_played, mark_done=True)


def tabs_shuffle() -> None:
    parser = argparse.ArgumentParser(prog="library tabs-shuffle", usage=usage.tabs_shuffle)
    parser.add_argument("--days", "-d", type=int, default=7)
    parser.add_argument(
        "--frequency",
        "-f",
        type=str.lower,
        help=f"One of: {', '.join(consts.frequency)} (default: %(default)s)",
    )
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_intermixed_args()

    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))

    tabs = list(
        args.db.query(
            f"""
        WITH m as (
            SELECT
                media.id
                , path
                , frequency
                , COALESCE(MAX(h.time_played), 0) time_last_played
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , hostname
                , category
            FROM media
            LEFT JOIN history h on h.media_id = media.id
            WHERE COALESCE(time_deleted, 0)=0
            GROUP BY media.id
        )
        SELECT
            id
            , path
            , frequency
            , time_last_played
        FROM m
        WHERE time_last_played > 0
            AND frequency != 'daily'
            {"AND frequency = '" + args.frequency + "'" if args.frequency else ''}
        """
        )
    )

    for d in tabs:
        # pick a random day within the same week
        date_last_played = datetime.fromtimestamp(d["time_last_played"])
        min_date = date_last_played - timedelta(days=args.days)

        min_time = int(min_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        max_time = d["time_last_played"]
        time_played = randint(min_time, max_time)

        with args.db.conn:  # type: ignore
            args.db.conn.execute(  # type: ignore
                "DELETE from history WHERE media_id = ? and time_played = ?", [d["id"], d["time_last_played"]]
            )
        history.add(args, [d["path"]], time_played=time_played, mark_done=True)
