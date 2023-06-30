import argparse
from pathlib import Path

from xklb import consts, db, history, usage, utils
from xklb.scripts.dedupe_db import dedupe_rows
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library copy-play-counts", usage=usage.copy_play_counts)
    parser.add_argument("database")
    parser.add_argument("source_dbs", nargs="+")
    parser.add_argument("--source-prefix", default="")
    parser.add_argument("--target-prefix", default="")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_intermixed_args()

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def copy_play_count(args, source_db) -> None:
    s_db = db.connect(argparse.Namespace(database=source_db, verbose=args.verbose))
    m_columns = s_db["media"].columns_dict

    copy_counts = []
    try:
        # TODO delete after 2024-06-01
        old_schema = list(
            s_db.query(
                f"""
                SELECT
                    path
                    , {', '.join(s for s in ['play_count', 'time_played', 'playhead'] if s in m_columns)}
                FROM
                    media
                WHERE
                    {' OR '.join(f"media.{s} > 0" for s in ['play_count', 'time_played', 'playhead'] if s in m_columns)}
                """,
            ),
        )

        new_schema = []
        for d in old_schema:
            if (d.get("play_count") or 0) == 0:
                new_schema.append({**d, "done": False})
            else:
                n = d.get("time_played") or consts.now()
                for i in range(d["play_count"]):
                    new_schema.append({**d, "done": True, "time_played": n + i})
        copy_counts.extend(new_schema)
    except Exception:
        log.info("Old schema could not be read")

    try:
        copy_counts.extend(
            list(
                s_db.query(
                    """
                SELECT
                    path
                    , h.time_played
                    , h.playhead
                    , done
                FROM
                    media m
                JOIN history h on h.media_id = m.id
                WHERE
                    h.time_played > 0
                    OR
                    h.playhead > 0
                """,
                ),
            ),
        )
    except Exception:
        log.exception("New schema could not be read")

    log.info(len(copy_counts))
    for d in copy_counts:
        renamed_path = d["path"].replace(args.source_prefix, args.target_prefix, 1)
        history.add(
            args,
            [renamed_path],
            time_played=d.get("time_played"),
            playhead=d.get("playhead"),
            mark_done=d["done"],
        )


def copy_play_counts() -> None:
    args = parse_args()
    history.create(args)
    for s_db in args.source_dbs:
        copy_play_count(args, s_db)
    dedupe_rows(args, "history", ["id"], ["media_id", "time_played"])


if __name__ == "__main__":
    copy_play_counts()
