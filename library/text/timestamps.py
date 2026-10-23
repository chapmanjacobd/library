import datetime

from dateutil.parser import parse

from library import usage
from library.utils import arggroups, argparse_utils, nums, strings
from library.utils.log_utils import log


def print_timestamp(n):
    nonzero_denominator = n % 1
    print(n if nonzero_denominator else int(n))


def _timestamp_parser(defaults_override=None, usage_override=None):
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
    return args


def _timestamp_preferences(args):
    date_order = {
        "month_day_year": (False, False),
        "day_month_year": (True, False),
        "year_month_day": (False, True),
        "year_day_month": (True, True),
    }
    selected_order = next((name for name in date_order if getattr(args, name)), None)
    day_first, year_first = date_order.get(selected_order, (None, None))

    if args.from_timezone:
        from_tzinfo = strings.timezone(args.from_timezone)
    elif args.from_unix:
        from_tzinfo = datetime.timezone.utc
    else:
        from_tzinfo = None

    if args.to_timezone:
        to_tzinfo = strings.timezone(args.to_timezone)
    elif args.to_unix:
        to_tzinfo = datetime.timezone.utc
    else:
        to_tzinfo = None

    return day_first, year_first, from_tzinfo, to_tzinfo


def _parse_timestamp(date_str, args, day_first, year_first, from_tzinfo):
    if args.from_unix:
        date = datetime.datetime.fromtimestamp(nums.safe_float(date_str), tz=datetime.timezone.utc)  # type: ignore
        date = date.replace(tzinfo=from_tzinfo)
    else:
        date = parse(
            date_str,
            default=datetime.datetime.now(tz=datetime.timezone.utc)
            .astimezone()
            .replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None),
            fuzzy=True,
            dayfirst=day_first,
            yearfirst=year_first,
        )
        if date.tzinfo is None:
            date = date.replace(tzinfo=from_tzinfo)

    log.debug("%s\t%s", date, date.tzinfo)
    return date


def _print_formatted_timestamp(date, args):
    if args.to_unix:
        if args.to_time_only:
            print_timestamp(date.hour * 3600 + date.minute * 60 + date.second + date.microsecond / 1e6)
        elif args.to_date_only:
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
        else:
            print_timestamp(date.timestamp())
        return

    if not args.print_timezone:
        date = date.replace(tzinfo=None)

    if args.to_time_only:
        date = date.time()
    elif args.to_date_only:
        date = date.date()

    print(date.isoformat())


def timestamps(defaults_override=None, usage_override=None):
    args = _timestamp_parser(defaults_override, usage_override)
    day_first, year_first, from_tzinfo, to_tzinfo = _timestamp_preferences(args)

    for date_str in args.dates:
        date = _parse_timestamp(date_str, args, day_first, year_first, from_tzinfo)

        date = date.astimezone(tz=to_tzinfo)
        log.debug("%s\t%s", date, date.tzinfo)
        _print_formatted_timestamp(date, args)


def times():
    timestamps({"to_time_only": True}, usage_override=usage.times)


def dates():
    timestamps({"to_date_only": True}, usage_override=usage.dates)
