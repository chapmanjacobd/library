import argparse

from library.mediadb import db_history
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, sqlgroups, strings

USAGE = {
    'history': """library database history [--frequency daily weekly (monthly) yearly] [--limit LIMIT] DATABASE [PATH ...] [(all) watching watched created modified deleted]

    View playback history

        library database history web_add.image.db
        In progress:
        play_count  time_last_played    playhead    path                                     title
        ------------  ------------------  ----------  ---------------------------------------  -----------
                0  today, 20:48        2 seconds   https://siliconpr0n.org/map/COPYING.txt  COPYING.txt

    Show only completed history

        library database history web_add.image.db --completed

    Show only completed history

        library database history web_add.image.db --in-progress

    Delete history

        Delete two hours of history
        library database history web_add.image.db --played-within '2 hours' -L inf --delete-rows

        Delete all history
        library database history web_add.image.db -L inf --delete-rows

        Delete history for exact paths
            library database history ~/mc/links.db --delete-rows https://example.com/article
            cb | library database history ~/mc/links.db --delete-rows -

        See also: library database stats -h
                  library database history add -h
""",
}


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=USAGE['history'])
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

    if args.delete_rows and not args.simulate:
        with args.db.conn:
            args.db.conn.execute("DELETE from history WHERE media_id NOT IN (SELECT id FROM media)")
        db_history.remove(args, paths=[d["path"] for d in tbl])
    elif args.delete_rows:
        print(f"Would delete orphaned history rows and {len(tbl)} matching history records")
    args.delete_rows = False
    media_printer.media_printer(args, tbl)
