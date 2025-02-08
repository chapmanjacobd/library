import argparse

from library import usage
from library.mediadb import db_history
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, sqlgroups


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.history)
    arggroups.sql_fs(parser)
    arggroups.history(parser)
    arggroups.debug(parser)

    arggroups.database(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)

    return args


def remove_duplicate_data(tbl):
    for d in tbl:
        if d.get("play_count", 0) <= 1:
            del d["time_first_played"]


def history() -> None:
    args = parse_args()
    db_history.create(args)

    if args.completed:
        print("Completed:")
    elif args.in_progress:
        print("In progress:")
    else:
        print("History:")

    tbl = list(args.db.query(*sqlgroups.historical_media(args)))
    remove_duplicate_data(tbl)

    if args.delete_rows:
        with args.db.conn:
            args.db.conn.execute("DELETE from history WHERE media_id NOT IN (SELECT id FROM media)")
        db_history.remove(args, paths=[d["path"] for d in tbl])
    args.delete_rows = False
    media_printer.media_printer(args, tbl)
