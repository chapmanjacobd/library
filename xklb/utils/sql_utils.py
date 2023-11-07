import re

from xklb.utils import db_utils
from xklb.utils.log_utils import log


def compare_block_strings(value, media_value):
    if value is None and media_value is None:
        return True
    elif value is None or media_value is None:
        return False

    value = value.lower()
    media_value = media_value.lower()

    starts_with_wild = value.startswith("%")
    ends_with_wild = value.endswith("%")
    inner_value = value.lstrip("%").rstrip("%")
    inner_wild = "%" in inner_value

    if inner_wild:
        regex_pattern = ".*".join(re.escape(s) for s in value.split("%"))
        return bool(re.match(regex_pattern, media_value))
    elif not ends_with_wild and not starts_with_wild:
        return media_value.startswith(value)
    elif ends_with_wild and not starts_with_wild:
        return media_value.startswith(value.rstrip("%"))
    elif starts_with_wild and not ends_with_wild:
        return media_value.endswith(value.lstrip("%"))
    elif starts_with_wild and ends_with_wild:
        return inner_value in media_value
    raise ValueError("Unreachable?")


def is_blocked_dict_like_sql(m, blocklist):
    for block_dict in blocklist:
        for key, value in block_dict.items():
            if key in m and compare_block_strings(value, m[key]):
                log.info("%s matched %s block rule 「%s」 %s", key, value, m[key], m.get("path"))
                return True
    return False


def block_dicts_like_sql(media, blocklist):
    return [m for m in media if not is_blocked_dict_like_sql(m, blocklist)]


def allow_dicts_like_sql(media, allowlist):
    allowed_media = []
    for m in media:
        is_blocked = False
        for block_dict in allowlist:
            for key, value in block_dict.items():
                if key in m and compare_block_strings(value, m[key]):
                    is_blocked = True
                    break
            if is_blocked:
                break
        if is_blocked:
            allowed_media.append(m)

    return allowed_media


def divide_sequence(arr):
    result = arr[0]
    if result == 0:
        return float("inf")
    elif 0 in arr:
        return float("-inf")
    for i in range(1, len(arr)):
        result = result / arr[i]
    return result


def sort_like_sql(order_bys):
    order_bys = [s.strip() for s in order_bys.split(",")]

    class Reversor:
        def __init__(self, obj):
            self.obj = obj

        def __eq__(self, other):
            return other.obj == self.obj

        def __lt__(self, other):
            return other.obj < self.obj

    def get_key(d):
        key = []
        for order in order_bys:
            if order.endswith(" desc"):
                order = order[:-5]
                reverse = True
            elif order.startswith("-"):
                order = order.lstrip("-")
                reverse = True
            else:
                reverse = False

            if "/" in order:
                vals = [d[s.strip()] for s in order.split("/")]
                val = divide_sequence(vals)
            else:
                val = d[order]

            key.append(Reversor(val) if reverse else val)

        return tuple(key)

    return get_key


def parse_human_to_sql(human_to_x, var, sizes) -> str:
    size_rules = ""

    for size in sizes:
        if ">" in size:
            size_rules += f"and {var} > {human_to_x(size.lstrip('>'))} "
        elif "<" in size:
            size_rules += f"and {var} < {human_to_x(size.lstrip('<'))} "
        elif "+" in size:
            size_rules += f"and {var} >= {human_to_x(size.lstrip('+'))} "
        elif "-" in size:
            size_rules += f"and {human_to_x(size.lstrip('-'))} >= {var} "
        else:
            # approximate size rule +-10%
            size_bytes = human_to_x(size)
            size_rules += (
                f"and {int(size_bytes + (size_bytes /10))} >= {var} and {var} >= {int(size_bytes - (size_bytes /10))} "
            )
    return size_rules


def parse_human_to_lambda(human_to_x, sizes):
    return lambda var: all(
        (
            (var > human_to_x(size.lstrip(">")))
            if ">" in size
            else (var < human_to_x(size.lstrip("<")))
            if "<" in size
            else (var >= human_to_x(size.lstrip("+")))
            if "+" in size
            else (human_to_x(size.lstrip("-")) >= var)
            if "-" in size
            else (
                int(human_to_x(size) + (human_to_x(size) / 10))
                >= var
                >= int(human_to_x(size) - (human_to_x(size) / 10))
            )
        )
        for size in sizes
    )


def frequency_time_to_sql(freq, time_column):
    if freq == "daily":
        freq_label = "day"
        freq_sql = f"strftime('%Y-%m-%d', datetime({time_column}, 'unixepoch'))"
    elif freq == "weekly":
        freq_label = "week"
        freq_sql = f"strftime('%Y-%W', datetime({time_column}, 'unixepoch'))"
    elif freq == "monthly":
        freq_label = "month"
        freq_sql = f"strftime('%Y-%m', datetime({time_column}, 'unixepoch'))"
    elif freq == "quarterly":
        freq_label = "quarter"
        freq_sql = f"strftime('%Y', datetime({time_column}, 'unixepoch', '-3 months')) || '-Q' || ((strftime('%m', datetime({time_column}, 'unixepoch', '-3 months')) - 1) / 3 + 1)"
    elif freq == "yearly":
        freq_label = "year"
        freq_sql = f"strftime('%Y', datetime({time_column}, 'unixepoch'))"
    elif freq == "decadally":
        freq_label = "decade"
        freq_sql = f"(CAST(strftime('%Y', datetime({time_column}, 'unixepoch')) AS INTEGER) / 10) * 10"
    elif freq == "hourly":
        freq_label = "hour"
        freq_sql = f"strftime('%Y-%m-%d %Hh', datetime({time_column}, 'unixepoch'))"
    elif freq == "minutely":
        freq_label = "minute"
        freq_sql = f"strftime('%Y-%m-%d %H:%M', datetime({time_column}, 'unixepoch'))"
    else:
        msg = f"Invalid value for 'freq': {freq}"
        raise ValueError(msg)
    return freq_label, freq_sql


def historical_usage_items(args, freq="monthly", time_column="time_modified", hide_deleted=False, where=""):
    m_columns = db_utils.columns(args, "media")

    freq_label, freq_sql = frequency_time_to_sql(freq, time_column)
    query = f"""SELECT
            {freq_sql} AS {freq_label}
            {', SUM(duration) AS total_duration' if 'duration' in m_columns else ''}
            {', AVG(duration) AS avg_duration' if 'duration' in m_columns else ''}
            {', SUM(size) AS total_size' if 'size' in m_columns else ''}
            {', AVG(size) AS avg_size' if 'size' in m_columns else ''}
            , count(*) as count
        FROM media m
        WHERE coalesce({freq_label}, 0)>0
            and {time_column}>0 {where}
            {"AND COALESCE(time_deleted, 0)=0" if hide_deleted else ""}
        GROUP BY {freq_label}
    """
    return list(args.db.query(query))


def historical_usage(args, freq="monthly", time_column="time_played", hide_deleted=False, where=""):
    freq_label, freq_sql = frequency_time_to_sql(freq, time_column)

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , *
            FROM media m
            JOIN history h on h.media_id = m.id
            WHERE 1=1
            {"AND COALESCE(time_deleted, 0)=0" if hide_deleted else ""}
            GROUP BY m.id, m.path
        )
        SELECT
            {freq_sql} AS {freq_label}
            , SUM(duration) AS total_duration
            , AVG(duration) AS avg_duration
            , SUM(size) AS total_size
            , AVG(size) AS avg_size
            , count(*) as count
        FROM m
        WHERE {time_column}>0 {where}
        GROUP BY {freq_label}
    """
    return list(args.db.query(query))
