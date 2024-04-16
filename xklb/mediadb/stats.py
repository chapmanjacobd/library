import argparse

from xklb import media_printer, usage
from xklb.utils import arggroups, consts, db_utils, objects, sql_utils, strings
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        "library stats",
        usage=usage.stats,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    arggroups.sql_fs(parser)
    arggroups.sql_media(parser)

    arggroups.frequency(parser)
    parser.add_argument("--hide-deleted", action="store_true")
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

    args.db = db_utils.connect(args)

    m_columns = db_utils.columns(args, "media")
    if args.facet not in m_columns:
        args.facet = "time_played"
    args.frequency = strings.partial_startswith(args.frequency, consts.frequency)

    args.action = consts.SC.stats
    log.info(objects.dict_filter_bool(args.__dict__))

    args.filter_bindings = {}

    return args


def process_search(args, m_columns):
    args.table = "media"
    if args.db["media"].detect_fts():
        if args.include:
            args.table, search_bindings = db_utils.fts_search_sql(
                "media",
                fts_table=args.db["media"].detect_fts(),
                include=args.include,
                exclude=args.exclude,
            )
            args.filter_bindings = search_bindings
        elif args.exclude:
            db_utils.construct_search_bindings(
                args,
                [f"m.{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
            )
    else:
        db_utils.construct_search_bindings(
            args,
            [f"m.{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
        )


def stats() -> None:
    args = parse_args()

    print(f"{args.facet.title()} media:")
    if args.facet == "time_played" or args.completed:
        tbl = sql_utils.historical_usage(args, args.frequency, args.facet, args.hide_deleted)
    else:
        tbl = sql_utils.historical_usage_items(args, args.frequency, args.facet, args.hide_deleted)
    media_printer.media_printer(args, tbl, units=args.frequency)


if __name__ == "__main__":
    stats()
