import argparse

from library import usage
from library.mediadb import db_history
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, sqlgroups, strings


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.history)
    arggroups.sql_fs(parser)
    arggroups.frequency(parser)
    arggroups.history(parser)
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser, required=False)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    arggroups.frequency_post(args)

    args.paths = [strings.strip_enclosing_quotes(path) for path in args.paths or []]
    arggroups.sql_fs_post(args)
    if args.paths:
        path_bindings = []
        for index, path in enumerate(args.paths):
            binding = f"history_path_{index}"
            path_bindings.append(f":{binding}")
            args.filter_bindings[binding] = path
        args.where.append(f"path IN ({', '.join(path_bindings)})")

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
