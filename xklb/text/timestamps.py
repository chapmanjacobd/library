import datetime

from dateutil.parser import parse

from xklb import usage
from xklb.utils import arggroups, argparse_utils, nums, strings
from xklb.utils.log_utils import log


def print_timestamp(n):
    nonzero_denominator = n % 1
    print(n if nonzero_denominator else int(n))


def timestamps(defaults_override=None, usage_override=None):
    parser = argparse_utils.ArgumentParser(usage=usage_override or usage.timestamps)
    parser.add_argument("--from-unix", "--unix", "-u", action="store_true", help="Parse from UNIX time")
    parser.add_argument("--from-timezone", "--from-tz", "-fz", help="Convert from timezone")

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

    parser.add_argument(
        "--to-date-only", "--date-only", "--date", "-d", action="store_true", help="Format the output as only dates"
    )
    parser.add_argument(
        "--to-time-only", "--time-only", "--time", "-t", action="store_true", help="Format the output as only times"
    )
    parser.add_argument("--to-unix", "-U", action="store_true", help="Format as UNIX time")
    parser.add_argument("--to-timezone", "--to-tz", "-tz", help="Convert to timezone")
    parser.add_argument("--print-timezone", "-TZ", action="store_true", help="Format with timezone")

    arggroups.debug(parser)

    parser.add_argument(
        "dates", nargs="*", default=argparse_utils.STDIN_DASH, action=argparse_utils.ArgparseArgsOrStdin
    )

    parser.set_defaults(**(defaults_override or {}))
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

    if args.from_timezone:
        from_tzinfo = strings.timezone(args.from_timezone)
    elif args.from_unix:
        from_tzinfo = datetime.timezone.utc  # this is needed to set the initial timezone
    else:
        from_tzinfo = None  # localtime

    if args.to_timezone:
        to_tzinfo = strings.timezone(args.to_timezone)
    elif args.to_unix:
        to_tzinfo = datetime.timezone.utc  # not really necessary but you can see the symmetry
    else:
        to_tzinfo = None  # localtime

    for date_str in args.dates:
        if args.from_unix:
            date = datetime.datetime.fromtimestamp(nums.safe_float(date_str), tz=datetime.timezone.utc)  # type: ignore
            date = date.replace(tzinfo=from_tzinfo)
            log.debug("%s\t%s", date, date.tzinfo)
        else:
            date = parse(
                date_str,
                default=datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                fuzzy=True,
                dayfirst=day_first,
                yearfirst=year_first,
            )
            log.debug("%s\t%s", date, date.tzinfo)
            if date.tzinfo is None:
                date = date.replace(tzinfo=from_tzinfo)  # naive datetime => timezone-aware datetime
                log.debug("%s\t%s", date, date.tzinfo)

        date = date.astimezone(tz=to_tzinfo)
        log.debug("%s\t%s", date, date.tzinfo)

        if args.to_unix:
            if args.to_time_only:  # datetime.time
                print_timestamp(date.hour * 3600 + date.minute * 60 + date.second + date.microsecond / 1e6)
            elif args.to_date_only:  # datetime.date
                print_timestamp(
                    datetime.datetime(
                        year=date.year,
                        month=date.month,
                        day=date.day,
                        hour=0,
                        minute=0,
                        microsecond=0,
                        tzinfo=date.tzinfo,
                    ).timestamp()
                )
            else:  # datetime.datetime
                print_timestamp(date.timestamp())
        else:
            if not args.print_timezone:
                date = date.replace(tzinfo=None)

            if args.to_time_only:
                date = date.time()
            elif args.to_date_only:
                date = date.date()

            print(date.isoformat())


def times():
    timestamps({"to_time_only": True}, usage_override=usage.times)


def dates():
    timestamps({"to_date_only": True}, usage_override=usage.dates)
