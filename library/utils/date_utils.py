import datetime

import dateutil.parser

from library.utils import iterables, nums


def super_parser(date_str):
    parsing_strategies = [
        {},  # default
        {"dayfirst": True},
        {"yearfirst": True},
        {"dayfirst": True, "yearfirst": True},
    ]
    for strategy in parsing_strategies:
        try:
            parsed_date = dateutil.parser.parse(date_str, fuzzy=True, **strategy)
            return parsed_date
        except dateutil.parser.ParserError:
            continue


def specific_date(*dates):
    valid_dates = [super_parser(s) for s in dates if s]
    past_dates = [d for d in valid_dates if d and d < datetime.datetime.now()]
    if not past_dates:
        return None

    earliest_specific_date = sorted(
        past_dates, key=lambda d: (bool(d.month), bool(d.day), -d.timestamp()), reverse=True
    )[0]
    return nums.to_timestamp(earliest_specific_date)


def tube_date(v):
    upload_date = iterables.safe_unpack(
        v.pop("release_date", None),
        v.pop("timestamp", None),
        v.pop("upload_date", None),
        v.pop("date", None),
        v.pop("created_at", None),
        v.pop("published", None),
        v.pop("updated", None),
    )
    if upload_date:
        if isinstance(upload_date, int) and upload_date > 30000000:
            return upload_date

        if isinstance(upload_date, datetime.datetime):
            upload_date = nums.to_timestamp(upload_date)
        else:
            try:
                upload_date = nums.to_timestamp(dateutil.parser.parse(str(upload_date)))
            except Exception:
                upload_date = None
    return upload_date


def utc_from_local_timestamp(n):
    return datetime.datetime.fromtimestamp(n).astimezone().astimezone(datetime.timezone.utc)
