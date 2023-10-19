import os, re, sys
from copy import deepcopy
from pathlib import Path
from typing import Dict, List

from xklb import db_media
from xklb.utils import consts, db_utils, iterables, processes, strings
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
            else:
                reverse = False

            key.append(Reversor(d[order]) if reverse else d[order])

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


def filter_args_sql(args, m_columns):
    return f"""
        {'and path like "http%"' if getattr(args, 'safe', False) else ''}
        {f'and path not like "{args.keep_dir}%"' if getattr(args, 'keep_dir', False) and Path(args.keep_dir).exists() else ''}
        {'and COALESCE(time_deleted,0) = 0' if 'time_deleted' in m_columns and 'deleted' not in ' '.join(sys.argv) else ''}
        {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
        {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
        {'AND COALESCE(time_downloaded,0) = 0' if args.online_media_only else ''}
        {'AND COALESCE(time_downloaded,1)!= 0 AND path not like "http%"' if args.local_media_only else ''}
    """


def get_dir_media(args, dirs: List, include_subdirs=False) -> List[Dict]:
    if len(dirs) == 0:
        return processes.no_media_found()

    m_columns = db_utils.columns(args, "media")

    if include_subdirs:
        filter_paths = "AND (" + " OR ".join([f"path LIKE :subpath{i}" for i in range(len(dirs))]) + ")"
    else:
        filter_paths = (
            "AND ("
            + " OR ".join([f"(path LIKE :subpath{i} and path not like :subpath{i} || '/%')" for i in range(len(dirs))])
            + ")"
        )

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , {args.select_sql}
                , m.*
            FROM media m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                AND COALESCE(time_deleted, 0)=0
                and m.id in (select id from {args.table})
                {filter_args_sql(args, m_columns)}
                {filter_paths}
                {'' if args.related >= consts.DIRS_NO_FILTER else (" ".join(args.filter_sql) or '')}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        ORDER BY play_count
            , m.path LIKE "http%"
            {', random()' if args.random else ''}
            {'' if 'sort' in args.defaults else ', ' + args.sort}
            , path
        {"LIMIT 10000" if 'limit' in args.defaults else str(args.limit)} {args.offset_sql}
    """
    subpath_params = {f"subpath{i}": value + "%" for i, value in enumerate(dirs)}

    bindings = {**subpath_params}
    if args.related >= consts.DIRS_NO_FILTER:
        bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("FTS")}}
    else:
        bindings = {**bindings, **args.filter_bindings}

    subpath_videos = list(args.db.query(query, bindings))
    log.debug(subpath_videos)
    log.info("len(subpath_videos) = %s", len(subpath_videos))

    return subpath_videos


def get_related_media(args, m: Dict) -> List[Dict]:
    m_columns = db_utils.columns(args, "media")
    m_columns.update(rank=int)

    m = db_media.get(args, m["path"])
    words = set(
        iterables.conform(
            strings.extract_words(m.get(k)) for k in m if k in db_utils.config["media"]["search_columns"]
        ),
    )
    args.include = sorted(words, key=len, reverse=True)[:100]
    log.info("related_words: %s", args.include)
    args.table, search_bindings = db_utils.fts_search_sql(
        "media",
        fts_table=args.db["media"].detect_fts(),
        include=args.include,
        exclude=args.exclude,
        flexible=True,
    )
    args.filter_bindings = {**args.filter_bindings, **search_bindings}

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , {args.select_sql}
                , rank
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                and path != :path
                {filter_args_sql(args, m_columns)}
                {'' if args.related >= consts.RELATED_NO_FILTER else (" ".join(args.filter_sql) or '')}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        ORDER BY play_count
            , m.path like "http%"
            , {'rank' if 'sort' in args.defaults else f'ntile(1000) over (order by rank), {args.sort}'}
            , path
        {"LIMIT " + str(args.limit - 1) if args.limit else ""} {args.offset_sql}
        """
    bindings = {"path": m["path"]}
    if args.related >= consts.RELATED_NO_FILTER:
        bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("FTS")}}
    else:
        bindings = {**bindings, **args.filter_bindings}

    related_videos = list(args.db.query(query, bindings))
    log.debug(related_videos)

    return [m, *related_videos]


def get_ordinal_media(args, m: Dict, ignore_paths=None) -> Dict:
    # TODO: maybe try https://dba.stackexchange.com/questions/43415/algorithm-for-finding-the-longest-prefix
    if ignore_paths is None:
        ignore_paths = []

    m_columns = db_utils.columns(args, "media")

    cols = args.cols or ["path", "title", "duration", "size", "subtitle_count", "is_dir"]
    args.select_sql = "\n        , ".join([c for c in cols if c in m_columns or c in ["*"]])

    total_media = args.db.execute("select count(*) val from media").fetchone()[0]
    candidate = deepcopy(m["path"])
    if args.play_in_order >= consts.SIMILAR_NO_FILTER_NO_FTS_PARENT:
        candidate = str(Path(candidate).parent)

    similar_videos = []
    while len(similar_videos) <= 1:
        if candidate == "":
            return m

        remove_chars = strings.last_chars(candidate)

        new_candidate = candidate[: -len(remove_chars)]
        log.debug(f"Matches for '{new_candidate}':")

        if candidate in ("" or new_candidate):
            return m

        candidate = new_candidate
        query = f"""WITH m as (
                SELECT
                    SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                    , MIN(h.time_played) time_first_played
                    , MAX(h.time_played) time_last_played
                    , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                    , {args.select_sql}
                FROM media m
                LEFT JOIN history h on h.media_id = m.id
                WHERE 1=1
                    AND COALESCE(time_deleted, 0)=0
                    and path like :candidate
                    {'' if args.play_in_order >= consts.SIMILAR_NO_FILTER_NO_FTS else f'and m.id in (select id from {args.table})'}
                    {filter_args_sql(args, m_columns)}
                    {'' if args.play_in_order >= consts.SIMILAR_NO_FILTER else (" ".join(args.filter_sql) or '')}
                    {"and path not in ({})".format(",".join([f":ignore_path{i}" for i in range(len(ignore_paths))])) if len(ignore_paths) > 0 else ''}
                GROUP BY m.id, m.path
            )
            SELECT
                *
            FROM m
            ORDER BY play_count, path
            LIMIT 1000
            """

        ignore_path_params = {f"ignore_path{i}": value for i, value in enumerate(ignore_paths)}
        bindings = {"candidate": candidate + "%", **ignore_path_params}
        if args.play_in_order >= consts.SIMILAR_NO_FILTER:
            if args.include or args.exclude:
                bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("FTS")}}
        else:
            bindings = {**bindings, **args.filter_bindings}

        similar_videos = list(args.db.query(query, bindings))
        log.debug(similar_videos)

        TOO_MANY_SIMILAR = 99
        if len(similar_videos) > TOO_MANY_SIMILAR or len(similar_videos) == total_media:
            return m

        if len(similar_videos) > 1:
            commonprefix = os.path.commonprefix([d["path"] for d in similar_videos])
            log.debug(commonprefix)
            PREFIX_LENGTH_THRESHOLD = 3
            if len(Path(commonprefix).name) < PREFIX_LENGTH_THRESHOLD:
                log.debug("Using commonprefix")
                return m

    return similar_videos[0]


def mark_media_deleted(args, paths) -> int:
    paths = iterables.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = iterables.chunks(paths, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""update media
                    set time_deleted={consts.APPLICATION_START}
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count
