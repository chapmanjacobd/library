import argparse

from library.mediadb import db_history
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, consts, db_utils, sql_utils

USAGE = {
    'stats': """library database stats DATABASE TIME_COLUMN

    View watched stats

        library database stats video.db --completed --no-hide-deleted

    View download stats

        library database stats video.db time_downloaded --frequency daily

        See also: library database stats video.db time_downloaded -f daily --hide-deleted

    View deleted stats

        library database stats video.db time_deleted --deleted

    View time_modified stats

        library database stats web_add.image.db time_modified -f year
        Time_Modified media:
        year      total_size    avg_size    count
        ------  ------------  ----------  -------
        2010         4.4 MiB     1.5 MiB        3
        2011       136.2 MiB    68.1 MiB        2
        2013         1.6 GiB    10.7 MiB      154
        2014         4.6 GiB    25.2 MiB      187
        2015         4.3 GiB    26.5 MiB      167
        2016         5.1 GiB    46.8 MiB      112
        2017         4.8 GiB    51.7 MiB       95
        2018         5.3 GiB    97.9 MiB       55
        2019         1.3 GiB    46.5 MiB       29
        2020        25.7 GiB   113.5 MiB      232
        2021        25.6 GiB    96.5 MiB      272
        2022        14.6 GiB    82.7 MiB      181
        2023        24.3 GiB    72.5 MiB      343
        2024        17.3 GiB   104.8 MiB      169
        14 media
""",
}


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=USAGE['stats'])
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

    if args.facet == "time_deleted" and "hide_deleted" in args.defaults:
        args.hide_deleted = False

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
