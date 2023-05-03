import argparse
from pathlib import Path

from xklb import db, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library copy-play-counts",
        usage="""library copy-play-counts DEST_DB SOURCE_DB ... [--source-prefix x] [--target-prefix y]

    Copy play count information between databases

        lb copy-play-counts audio.db phone.db --source-prefix /storage/6E7B-7DCE/d --target-prefix /mnt/d
""",
    )
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

    for col in ["play_count", "time_played"]:
        modified_row_count = 0
        with args.db.conn:
            sql = f"""
            UPDATE
                main.media
            SET
                {col} = (
                    SELECT
                        {col}
                    FROM
                        src.media
                    WHERE
                        main.media.path = REPLACE(src.media.path, :source_prefix, :target_prefix)
                )
            WHERE
                EXISTS(
                    SELECT
                        1
                    FROM
                        src.media
                    WHERE
                        main.media.path = REPLACE(src.media.path, :source_prefix, :target_prefix)
                        AND src.media.play_count > 0
                );
            """
            cursor = args.db.conn.execute(
                sql, {"source_prefix": args.source_prefix, "target_prefix": args.target_prefix}
            )
            modified_row_count += cursor.rowcount

        log.info("Updated %s rows (%s)", modified_row_count, col)


def copy_play_counts() -> None:
    args = parse_args()
    for s_db in args.source_dbs:
        copy_play_count(args, s_db)


if __name__ == "__main__":
    copy_play_counts()
