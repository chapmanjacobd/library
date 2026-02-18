import re, sys
from contextlib import suppress
from pathlib import Path
from random import random
from typing import Any

from library.utils import consts, db_utils, file_utils, iterables, processes
from library.utils.log_utils import log
from library.utils.objects import Reverser


def sort_like_sql(order_bys: str):
    order_bys_list = [s.strip() for s in order_bys.split(",")]

    def get_key(d):
        key = []
        for order in order_bys_list:
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
                val = iterables.divide_sequence(vals)
            else:
                val = d[order]

            key.append(Reverser(val) if reverse else val)

        return tuple(key)

    return get_key


def media_select_sql(args, m_columns):
    if args.action in (consts.SC.disk_usage, consts.SC.big_dirs):
        default_cols = ["path", "duration", "size", "rank"]
    else:
        default_cols = ["path", "title", "duration", "size", "rank"]

    cols = args.cols or default_cols
    if "deleted" in " ".join(sys.argv):
        cols.append("time_deleted")
    if "played" in " ".join(sys.argv):
        cols.append("time_last_played")
    args.select = list(
        iterables.ordered_set([c for c in cols if c in m_columns or c in ["*"]] + getattr(args, "select", []))
    )
    if args.action == consts.SC.read and "tags" in m_columns:
        if "duration" in args.select:
            args.select.remove("duration")
        args.select += ["cast(length(tags) / 4.2 / 220 * 60 as INT) + 10 duration"]

    if not args.select:
        processes.exit_error("No columns to query. No table in sqlite file?")

    select_sql = "\n        , ".join(args.select)
    return select_sql


def perf_randomize_using_ids(args):
    if args.random and not args.include and not args.print and args.limit in args.defaults:
        limit = 16 * (args.limit or consts.DEFAULT_PLAY_QUEUE)
        where_not_deleted = "where COALESCE(time_deleted,0) = 0" if args.hide_deleted else ""
        args.filter_sql.append(
            f"and m.rowid in (select rowid as id from media {where_not_deleted} order by random() limit {limit})",
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


def filter_episodic(args, items: list[dict]) -> list[dict]:
    parent_dict = {}
    for m in items:
        path = Path(m["path"])
        parent_path = path.parent
        parent_dict.setdefault(parent_path, 0)
        parent_dict[parent_path] += 1

    filtered_items = []
    for m in items:
        path = Path(m["path"])
        parent_path = path.parent

        siblings = parent_dict[parent_path]

        if not args.file_counts(siblings):
            continue
        else:
            filtered_items.append(m)

    return filtered_items


def history_sort(args, items: list[dict]) -> list[dict]:
    if "s" in args.partial:  # skip; only play unseen
        previously_watched_paths = [m["path"] for m in items if m["time_first_played"]]
        return [m for m in items if m["path"] not in previously_watched_paths]

    def mpv_progress(m):
        playhead = m.get("playhead")
        duration = m.get("duration")
        if not playhead:
            return float("-inf")
        if not duration:
            return float("-inf")

        if "p" in args.partial and "t" in args.partial:
            return (duration / playhead) * -(duration - playhead)  # weighted remaining
        elif "t" in args.partial:
            return -(duration - playhead)  # time remaining
        else:
            return playhead / duration  # percent remaining

    def sorting_hat():
        if "f" in args.partial:  # first-viewed
            return lambda m: m.get("time_first_played") or 0
        elif "p" in args.partial or "t" in args.partial:  # sort by remaining duration
            return mpv_progress

        return lambda m: m.get("time_last_played") or m.get("time_first_played") or 0

    reverse_chronology = True
    if "o" in args.partial:  # oldest first
        reverse_chronology = False

    key = sorting_hat()
    if args.print:
        reverse_chronology = not reverse_chronology

    items = sorted(items, key=key, reverse=reverse_chronology)

    if args.offset:
        items = items[int(args.offset) :]

    return items


def limit_sql(limit, offset, limit_adj=0) -> str:
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
        m_columns = {*m_columns, "rank"}
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


def eval_sql_expr(key: str, op: str, val: str, item: dict) -> bool:
    """Evaluate a simplified SQL-like operator expression on item."""
    col_val = item.get(key)
    val = val.strip("'\"")

    if op == "LIKE":
        # SQLite LIKE -> translate %/_ to regex
        regex = "^" + re.escape(val).replace("%", ".*").replace("_", ".") + "$"
        return bool(re.match(regex, str(col_val or ""), flags=re.IGNORECASE))
    elif op == "IS" and val.upper() == "NULL":
        return col_val is None

    if col_val is None:
        return False

    # Try to convert to the same type as col_val
    target_val: Any = val
    if isinstance(col_val, int):
        with suppress(ValueError):
            target_val = int(val)
    elif isinstance(col_val, float):
        with suppress(ValueError):
            target_val = float(val)

    if op in ("=", "=="):
        return col_val == target_val
    elif op in ("!=", "<>"):
        return col_val != target_val
    elif op == ">":
        return col_val > target_val
    elif op == "<":
        return col_val < target_val
    elif op == ">=":
        return col_val >= target_val
    elif op == "<=":
        return col_val <= target_val
    else:
        msg = f"Unsupported operator: {op}"
        raise ValueError(msg)


def is_mime_match(types: list[str], mime_type: str) -> bool:
    if not mime_type:
        return False

    # exact match
    for type_ in types:
        is_match = mime_type == type_
        if is_match:
            return True

    # substring match
    mime_type = mime_type.replace("<", "").replace(">", "")
    mime_type_words = [word for word in re.split(r"[ /]+", mime_type) if word]

    if not mime_type_words:
        return False

    for type_ in types:
        is_case_sensitive = not type_.islower()

        for word in mime_type_words:
            is_match = word == type_ if is_case_sensitive else word.lower() == type_.lower()
            if is_match:
                return True

    return False


def filter_mimetype(args, files):
    if getattr(args, "type", None) or getattr(args, "no_type", None):
        files = [d if "type" in d else file_utils.get_file_type(d) for d in files]
    if getattr(args, "no_type", None):
        files = [d for d in files if not is_mime_match(args.no_type, d["type"] or "None")]
    if getattr(args, "type", None):
        files = [d for d in files if is_mime_match(args.type, d["type"] or "None")]

    return files


def sort_items_by_criteria(args, items):
    def normalize_key(key: str) -> str:
        """Remove table prefixes like m.path -> path."""
        return key.split(".")[-1]

    def get_sort_key(item):
        sort_values = []
        if not getattr(args, "sort", None):
            return tuple()

        sort_exprs = args.sort if isinstance(args.sort, list) else args.sort.split(",")
        for s in sort_exprs:
            parts = s.strip().split()
            if not parts:
                continue
            reverse = parts[-1].lower() == "desc"
            key = normalize_key(parts[0])

            if len(parts) == 1 or (len(parts) == 2 and parts[1].lower() in ("asc", "desc")):
                # simple column
                if key.lower() == "random()":
                    value = random()
                else:
                    value = item.get(key)
            else:
                # operator form: col OP val [ASC|DESC]
                op = parts[1].upper()
                val = " ".join(parts[2:-1]) if reverse else " ".join(parts[2:])
                value = eval_sql_expr(key, op, val, item)

            if value is None:
                value = "" if isinstance(item.get("path"), str) else 0

            sort_values.append(Reverser(value) if reverse else value)

        return tuple(sort_values)

    return sorted(items, key=get_sort_key)


def filter_items_by_criteria(args, items):
    if "sizes" not in getattr(args, "defaults", []):
        size_exists, items = iterables.peek_value_exists(items, "size")
        if not size_exists:
            items = file_utils.get_files_stats(items)
        items = [d for d in items if args.sizes(d["size"])]
    elif "size" in getattr(args, "sort", []):
        size_exists, items = iterables.peek_value_exists(items, "size")
        if not size_exists:
            items = file_utils.get_files_stats(items)

    items = filter_mimetype(args, items)

    if getattr(args, "time_created", []):
        items = [d if "time_created" in d else file_utils.get_file_stats(d) for d in items]
        items = [
            d
            for d in items
            if d["time_created"] > 0 and args.time_created(consts.APPLICATION_START - d["time_created"])  # type: ignore
        ]
    if getattr(args, "time_modified", []):
        items = [d if "time_modified" in d else file_utils.get_file_stats(d) for d in items]
        items = [
            d
            for d in items
            if d["time_modified"] > 0 and args.time_modified(consts.APPLICATION_START - d["time_modified"])  # type: ignore
        ]

    if getattr(args, "to_json", False):
        items = [d if "size" in d else file_utils.get_file_stats(d) for d in items]
        items = [d if "type" in d else file_utils.get_file_type(d) for d in items]

    if items and getattr(args, "sort", []):
        items = sort_items_by_criteria(args, items)

    if items and getattr(args, "limit", []):
        items = items[: args.limit]

    return list(items)


class FilterEngine:
    def __init__(self, args):
        self.args = args

    def apply_memory_filters(self, items: list[dict]) -> list[dict]:
        return filter_items_by_criteria(self.args, items)

    def apply_sql_filters(self, m_columns, table="media", table_prefix="m."):
        return search_filter(self.args, m_columns, table=table, table_prefix=table_prefix)

    def sort_items(self, items: list[dict]) -> list[dict]:
        return sort_items_by_criteria(self.args, items)

    def apply_post_filters(self, items: list[dict]) -> list[dict]:
        if getattr(self.args, "file_counts", None):
            items = filter_episodic(self.args, items)
        if getattr(self.args, "partial", None):
            items = history_sort(self.args, items)
        return items

    def get_filtered_data(self, db_sql_func: Any = None, fs_gen_func: Any = None) -> list[dict]:
        if self.args.database:
            if db_sql_func is None:
                raise ValueError("db_sql_func is required when using database")
            query, bindings = db_sql_func(self.args)
            items = list(self.args.db.query(query, bindings))
            items = filter_mimetype(self.args, items)
        else:
            if fs_gen_func is None:
                raise ValueError("fs_gen_func is required when not using database")
            items = fs_gen_func(self.args)
            items = self.apply_memory_filters(items)

        if not items:
            processes.no_media_found()
        return items


def human_to_lambda_part(var: Any, human_to_x: Any, size: str) -> bool:
    if var is None:
        var = 0

    if size.startswith(">"):
        return var > human_to_x(size.lstrip(">"))
    elif size.startswith("<"):
        return var < human_to_x(size.lstrip("<"))
    elif size.startswith("+"):
        return var >= human_to_x(size.lstrip("+"))
    elif size.startswith("-"):
        return human_to_x(size.lstrip("-")) >= var
    elif "%" in size:
        size_str, percent_str = size.split("%")
        val = float(human_to_x(size_str))
        percent = float(percent_str)
        lower_bound = val - (val * (percent / 100))
        upper_bound = val + (val * (percent / 100))
        return lower_bound <= float(var) and float(var) <= upper_bound
    else:
        return var == human_to_x(size)


def human_to_sql_part(human_to_x: Any, var: str, size: str) -> str:
    if size.startswith(">"):
        return f"and {var} > {human_to_x(size.lstrip('>'))} "
    elif size.startswith("<"):
        return f"and {var} < {human_to_x(size.lstrip('<'))} "

    elif size.startswith("+"):
        return f"and {var} >= {human_to_x(size.lstrip('+'))} "
    elif size.startswith("-"):
        return f"and {var} <= {human_to_x(size.lstrip('-'))} "

    elif "%" in size:
        size_str, percent_str = size.split("%")
        val = float(human_to_x(size_str))
        percent = float(percent_str)
        lower_bound = int(val - (val * (percent / 100)))
        upper_bound = int(val + (val * (percent / 100)))
        return f"and {lower_bound} <= {var} and {var} <= {upper_bound} "
    else:
        return f"and {var} = {human_to_x(size)} "


def parse_human_to_sql(human_to_x, var, sizes: list[str]) -> str:
    size_rules = ""
    for size in sizes:
        size_rules += human_to_sql_part(human_to_x, var, size)

    return size_rules


def parse_human_to_lambda(human_to_x, sizes: list[str]):
    if not sizes:
        return lambda _var: True

    def check_all_sizes(var):
        return all(human_to_lambda_part(var, human_to_x, size) for size in sizes)

    return check_all_sizes


def compare_block_strings(value: str, media_value: str) -> bool:
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


def is_blocked_dict_like_sql(m: dict, blocklist: list[dict]) -> bool:
    for block_dict in blocklist:
        for key, value in block_dict.items():
            if key in m and compare_block_strings(value, m[key]):
                log.info("%s matched %s block rule 「%s」 %s", key, value, m[key], m.get("path"))
                return True
    return False


def block_dicts_like_sql(media: list[dict], blocklist: list[dict]) -> list[dict]:
    return [m for m in media if not is_blocked_dict_like_sql(m, blocklist)]


def allow_dicts_like_sql(media: list[dict], allowlist: list[dict]) -> list[dict]:
    allowed_media = []
    for m in media:
        is_allowed = False
        for allow_dict in allowlist:
            for key, value in allow_dict.items():
                if key in m and compare_block_strings(value, m[key]):
                    is_allowed = True
                    break
            if is_allowed:
                break
        if is_allowed:
            allowed_media.append(m)

    return allowed_media
