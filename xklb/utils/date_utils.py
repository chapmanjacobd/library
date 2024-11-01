import datetime

import dateutil.parser

from xklb.utils import iterables, nums


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
                upload_date = nums.to_timestamp(dateutil.parser.parse(upload_date))
            except Exception:
                upload_date = None
    return upload_date


def utc_from_local_timestamp(n):
    return datetime.datetime.fromtimestamp(n).astimezone().astimezone(datetime.timezone.utc)
