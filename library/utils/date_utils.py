import datetime
from datetime import timezone as tz

import dateutil.parser

from library.utils import iterables, nums


def is_tz_aware(dt: datetime.datetime) -> bool:
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def maybe_tz_now(maybe_tz_dt: datetime.datetime):
    if is_tz_aware(maybe_tz_dt):
        now = datetime.datetime.now(tz=tz.utc).astimezone()
    else:
        now = datetime.datetime.now()
    return now


def super_parser(date_str, fallback=False):
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

    if fallback:
        return date_str


def specific_date(*dates):
    valid_dates = [super_parser(s) for s in dates if s]
    past_dates = [d for d in valid_dates if d and d < maybe_tz_now(d)]
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
