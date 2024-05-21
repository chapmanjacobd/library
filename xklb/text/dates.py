import datetime, sys

from dateutil.parser import parse

from xklb import usage
from xklb.utils import arggroups, argparse_utils


def dates():
    parser = argparse_utils.ArgumentParser(usage=usage.dates)
    parser.add_argument("--timestamp", "--time", action="store_true", help="Parse the input as timestamp")
    parser.add_argument("--time-only", action="store_true", help="Parse the input as time")

    parser.add_argument(
        "--month-day-year",
        "-m-d-y",
        action="store_true",
        help="""Parse ambiguous 3-integer date as MDY (default)
Example: 01/10/05
MDY  2005-01-10
DMY  2005-10-01
YMD  2001-10-05
YDM  2001-05-10

Example: July 8th, 2009
MDY  07/08/09
DMY  08/07/09
YMD  09/07/08
YDM  09/08/07
""",
    )
    parser.add_argument("--day-month-year", "-d-m-y", action="store_true", help="Parse ambiguous 3-integer date as DMY")
    parser.add_argument("--year-month-day", "-y-m-d", action="store_true", help="Parse ambiguous 3-integer date as YMD")
    parser.add_argument("--year-day-month", "-y-d-m", action="store_true", help="Parse ambiguous 3-integer date as YDM")
    arggroups.debug(parser)

    parser.add_argument(
        "dates", nargs="*", default=argparse_utils.STDIN_DASH, action=argparse_utils.ArgparseArgsOrStdin
    )
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    day_first = None
    year_first = None
    if args.month_day_year:
        day_first = False
        year_first = False
    elif args.day_month_year:
        day_first = True
        year_first = False
    elif args.year_month_day:
        day_first = False
        year_first = True
    elif args.year_day_month:
        day_first = True
        year_first = True

    for date_str in args.dates:
        date = parse(
            date_str,
            default=datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            fuzzy=True,
            dayfirst=day_first,
            yearfirst=year_first,
        )

        if args.time_only:
            date = date.time()
        elif args.timestamp:
            pass
        else:
            date = date.date()

        print(date.isoformat())


def times():
    sys.argv += ["--timestamp"]
    dates()
