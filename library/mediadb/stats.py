import argparse

from library import usage
from library.mediadb import db_history
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, consts, db_utils, sql_utils


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.stats)
    arggroups.sql_fs(parser)
    arggroups.frequency(parser)
    arggroups.history(parser)
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument(
        "facet",
        metavar="facet",
        type=str.lower,
        default="watched",
        const="watched",
        nargs="?",
        help=f"One of: {', '.join(consts.time_facets)}",
    )
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    m_columns = db_utils.columns(args, "media")
    if args.facet not in m_columns:
        args.facet = "time_played"

    arggroups.sql_fs_post(args)
    arggroups.frequency_post(args)

    return args


def stats() -> None:
    args = parse_args()
    db_history.create(args)

    print(f"{args.facet.title()} media:")
    if args.facet == "time_played" or args.completed:
        tbl = sql_utils.historical_usage(args, args.frequency, args.facet, args.hide_deleted, args.only_deleted)
    else:
        tbl = sql_utils.historical_usage_items(args, args.frequency, args.facet, args.hide_deleted, args.only_deleted)
    media_printer.media_printer(args, tbl, units=args.frequency)
