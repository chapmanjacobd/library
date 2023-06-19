import argparse
from pathlib import Path

from xklb import db, history, usage, utils
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
    args.db.attach("src", Path(source_db).resolve())

    copy_counts = []
    try:
        # TODO delete after 2024-06-01
        old_schema = list(
            args.db.query(
                """
                SELECT
                    path, play_count, time_played, playhead
                FROM
                    src.media
                WHERE
                    src.media.play_count > 0
                    OR
                    src.media.playhead > 0
                """,
            ),
        )

        new_schema = []
        for d in old_schema:
            if d["playhead"] is None or d["playhead"] == 0:
                new_schema.append(
                    {"path": d["path"], "time_played": d["time_played"], "playhead": d["playhead"], "done": False},
                )
            else:
                for _ in range(d["playhead"]):
                    new_schema.append(
                        {"path": d["path"], "time_played": d["time_played"], "playhead": d["playhead"], "done": True},
                    )
        copy_counts.extend(new_schema)
    except:
        log.info("Old schema playhead could not be read")

    try:
        copy_counts.extend(
            list(
                args.db.query(
                    """
                SELECT
                    path, time_played, playhead, done
                FROM
                    src.media m
                JOIN src.history h on h.media_id = m.id
                WHERE
                    h.time_played > 0
                    OR
                    h.playhead > 0
                """,
                ),
            ),
        )
    except:
        log.info("New schema playhead could not be read")

    for d in copy_counts:
        renamed_path = d["path"].replace(args.source_prefix, args.target_prefix, 1)
        history.add(args, [renamed_path], time_played=d["time_played"], playhead=d["playhead"], mark_done=d["done"])


def copy_play_counts() -> None:
    args = parse_args()
    for s_db in args.source_dbs:
        copy_play_count(args, s_db)
    dedupe_rows(args, "history", ["id"], ["media_id", "time_played"])


if __name__ == "__main__":
    copy_play_counts()
