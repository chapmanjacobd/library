import argparse

from xklb import usage
from xklb.editdb import dedupe_db
from xklb.mediadb import db_history
from xklb.utils import arggroups, argparse_utils, db_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library copy-play-counts", usage=usage.copy_play_counts)
    parser.add_argument("--source-prefix", default="")
    parser.add_argument("--target-prefix", default="")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("source_dbs", nargs="+")
    args = parser.parse_intermixed_args()

    arggroups.args_post(args, parser, create_db=True)
    return args


def copy_play_count(args, source_db) -> None:
    s_db = db_utils.connect(argparse.Namespace(database=source_db, verbose=args.verbose))
    m_columns = s_db["media"].columns_dict

    copy_counts = list(
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
    )

    log.info(len(copy_counts))
    for d in copy_counts:
        renamed_path = d["path"].replace(args.source_prefix, args.target_prefix, 1)
        db_history.add(
            args,
            [renamed_path],
            time_played=d.get("time_played"),
            playhead=d.get("playhead"),
            mark_done=d["done"],
        )


def copy_play_counts() -> None:
    args = parse_args()
    db_history.create(args)
    for s_db in args.source_dbs:
        copy_play_count(args, s_db)
    dedupe_db.dedupe_rows(args, "history", ["id"], ["media_id", "time_played"])


if __name__ == "__main__":
    copy_play_counts()
