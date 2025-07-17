import re

from library.utils import consts, db_utils, nums
from library.utils.iterables import divide_sequence
from library.utils.log_utils import log
from library.utils.objects import Reverser


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


def sort_like_sql(order_bys):
    order_bys = [s.strip() for s in order_bys.split(",")]

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

            key.append(Reverser(val) if reverse else val)

        return tuple(key)

    return get_key


def human_to_sql_part(human_to_x, var, size):
    if size.startswith(">"):
        return f"and {var} > {human_to_x(size.lstrip('>'))} "
    elif size.startswith("<"):
        return f"and {var} < {human_to_x(size.lstrip('<'))} "

    elif size.startswith("+"):
        return f"and {var} >= {human_to_x(size.lstrip('+'))} "
    elif size.startswith("-"):
        return f"and {var} <= {human_to_x(size.lstrip('-'))} "

    elif "%" in size:
        size, percent = size.split("%")
        size = human_to_x(size)
        percent = float(percent)
        lower_bound = int(size - (size * (percent / 100)))
        upper_bound = int(size + (size * (percent / 100)))
        return f"and {lower_bound} <= {var} and {var} <= {upper_bound} "
    else:
        return f"and {var} = {human_to_x(size)} "


def parse_human_to_sql(human_to_x, var, sizes) -> str:
    size_rules = ""
    for size in sizes:
        size_rules += human_to_sql_part(human_to_x, var, size)

    return size_rules


def human_to_lambda_part(var, human_to_x, size):
    if var is None:
        var = 0

    if size.startswith(">"):
        return var > human_to_x(size.lstrip(">"))
    elif size.startswith("<"):
        return var < human_to_x(size.lstrip("<"))
    elif size.startswith("+"):
        return var > human_to_x(size.lstrip("+"))
    elif size.startswith("-"):
        return human_to_x(size.lstrip("-")) >= var
    elif "%" in size:
        size, percent = size.split("%")
        size = human_to_x(size)
        percent = float(percent)
        lower_bound = int(size - (size * (percent / 100)))
        upper_bound = int(size + (size * (percent / 100)))
        return lower_bound <= var and var <= upper_bound
    else:
        return var == human_to_x(size)


def parse_human_to_lambda(human_to_x, sizes):
    if not sizes:
        return lambda _var: True

    def check_all_sizes(var):
        return all(human_to_lambda_part(var, human_to_x, size) for size in sizes)

    return check_all_sizes


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


def historical_usage_items(
    args, freq="monthly", time_column="time_modified", hide_deleted=False, only_deleted=False, where=None
):
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
            and {time_column}>0 {where or ''}
            {"AND COALESCE(time_deleted, 0)=0" if hide_deleted else ""}
            {"AND COALESCE(time_deleted, 0)>0" if only_deleted else ""}
        GROUP BY {freq_label}
        ORDER BY {freq_label} desc
    """

    return list(args.db.query(query))


def filter_time_played(args):
    sql = []
    played_before = args.played_before or args.created_before
    played_within = args.played_within or args.created_within
    if played_before:
        played_before = nums.sql_human_time(played_before)
        sql.append(f"and h.time_played < cast(STRFTIME('%s', datetime( 'now', '-{played_before}')) as int)")
    if played_within:
        played_within = nums.sql_human_time(played_within)
        sql.append(f"and h.time_played >= cast(STRFTIME('%s', datetime( 'now', '-{played_within}')) as int)")

    return " ".join(sql)


def filter_play_count(args):
    sql = []

    if getattr(args, "completed", False):
        sql.append("and coalesce(play_count, 0)>0")
    if getattr(args, "in_progress", False):
        sql.append("and coalesce(play_count, 0)=0")

    return " ".join(sql)


def historical_usage(args, freq="monthly", time_column="time_played", hide_deleted=False, only_deleted=False):
    freq_label, freq_sql = frequency_time_to_sql(freq, time_column)
    m_columns = args.db["media"].columns_dict
    h_columns = args.db["history"].columns_dict

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                {', FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead' if 'playhead' in h_columns else ''}
                , *
            FROM media m
            JOIN history h on h.media_id = m.rowid
            WHERE 1=1
            {filter_time_played(args)}
            {"AND COALESCE(time_deleted, 0)=0" if hide_deleted else ""}
            {"AND COALESCE(time_deleted, 0)>0" if only_deleted else ""}
            GROUP BY m.rowid, m.path
        )
        SELECT
            {freq_sql} AS {freq_label}
            {', SUM(duration) AS total_duration' if 'duration' in m_columns else ''}
            {', AVG(duration) AS avg_duration' if 'duration' in m_columns else ''}
            {', SUM(size) AS total_size' if 'size' in m_columns else ''}
            {', AVG(size) AS avg_size' if 'size' in m_columns else ''}
            , count(*) as count
        FROM m
        WHERE {time_column}>0
            {filter_play_count(args)}
        GROUP BY {freq_label}
        ORDER BY {freq_label} desc
    """

    return list(args.db.query(query))


def limit_sql(limit, offset, limit_adj=0):
    sql = f"LIMIT {limit + limit_adj}" if limit else "LIMIT -1" if offset else ""
    offset_sql = f"OFFSET {offset}" if offset else ""
    sql = f"{sql} {offset_sql}"
    return sql


def fts_quote(query: list[str]) -> list[str]:
    fts_words = [" NOT ", " AND ", " OR ", "*", ":", "NEAR("]
    return [s if any(r in s for r in fts_words) else '"' + s + '"' for s in query]


def fts_search_sql(table, fts_table, include, exclude=None, flexible=False):
    param_key = "S_FTS_" + consts.random_string()
    table = f"""(
    with original as (select rowid, * from [{table}])
    select
        [original].*
        , [{fts_table}].rank
    from
        [original]
        join [{fts_table}] on [original].rowid = [{fts_table}].rowid
    where
        [{fts_table}] match :{param_key}
    )
    """
    if flexible:
        param_value = " OR ".join(fts_quote(include))
    else:
        param_value = " AND ".join(fts_quote(include))
    if exclude:
        param_value += " NOT " + " NOT ".join(fts_quote(exclude))

    bound_parameters = {param_key: param_value}
    return table, bound_parameters


def construct_search_bindings(include, exclude, columns, exact=False, flexible_search=False):
    param_key = "S_" + consts.random_string()

    sql = []
    bindings = {}

    incl = ":" + param_key + "include{0}"
    includes = "(" + " OR ".join([f"{col} LIKE {incl}" for col in columns]) + ")"
    includes_sql_parts = []
    for idx, inc in enumerate(include):
        includes_sql_parts.append(includes.format(idx))
        if exact:
            bindings[f"{param_key}include{idx}"] = inc
        else:
            bindings[f"{param_key}include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    join_op = " OR " if flexible_search else " AND "
    if len(includes_sql_parts) > 0:
        sql.append("AND (" + join_op.join(includes_sql_parts) + ")")

    excl = ":" + param_key + "exclude{0}"
    excludes = "AND (" + " AND ".join([f"COALESCE({col},'') NOT LIKE {excl}" for col in columns]) + ")"
    for idx, exc in enumerate(exclude):
        sql.append(excludes.format(idx))
        if exact:
            bindings[f"{param_key}exclude{idx}"] = exc
        else:
            bindings[f"{param_key}exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"

    return sql, bindings


def search_filter(args, m_columns, table="media", table_prefix="m."):
    if args.db[table].detect_fts() and args.fts and args.include:
        table, search_bindings = fts_search_sql(
            table,
            fts_table=args.db[table].detect_fts(),
            include=args.include,
            exclude=args.exclude,
            flexible=args.flexible_search,
        )
        args.filter_bindings = {**args.filter_bindings, **search_bindings}
        m_columns = {**m_columns, "rank": int}
    else:  # only exclude or no-fts
        search_sql, search_bindings = construct_search_bindings(
            include=args.include,
            exclude=args.exclude,
            columns=[
                f"{table_prefix}{k}"
                for k in m_columns
                if k in db_utils.config[table]["search_columns"]
                if k in m_columns
            ],
            exact=args.exact,
            flexible_search=args.flexible_search,
        )
        args.filter_sql.extend(search_sql)
        args.filter_bindings = {**args.filter_bindings, **search_bindings}

    return table, m_columns
