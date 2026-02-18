from library.utils import db_utils, filter_engine, nums

compare_block_strings = filter_engine.compare_block_strings
is_blocked_dict_like_sql = filter_engine.is_blocked_dict_like_sql
block_dicts_like_sql = filter_engine.block_dicts_like_sql
allow_dicts_like_sql = filter_engine.allow_dicts_like_sql
human_to_lambda_part = filter_engine.human_to_lambda_part
parse_human_to_lambda = filter_engine.parse_human_to_lambda
human_to_sql_part = filter_engine.human_to_sql_part
parse_human_to_sql = filter_engine.parse_human_to_sql
sort_like_sql = filter_engine.sort_like_sql
frequency_time_to_sql = filter_engine.frequency_time_to_sql


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
        WHERE 1=1
            and {time_column}>0 {where or ''}
            -- coalesce({freq_label}, 0)>0 -- not sure what my intention was here
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


limit_sql = filter_engine.limit_sql
fts_quote = filter_engine.fts_quote
fts_search_sql = filter_engine.fts_search_sql
construct_search_bindings = filter_engine.construct_search_bindings
search_filter = filter_engine.search_filter
sort_like_sql = filter_engine.sort_like_sql
