import sys

from xklb.utils import consts, db_utils, sql_utils
from xklb.utils.consts import SC


def media_select_sql(args, m_columns):
    cols = args.cols or ["path", "title", "duration", "size", "rank"]
    if "deleted" in " ".join(sys.argv):
        cols.append("time_deleted")
    if "played" in " ".join(sys.argv):
        cols.append("time_last_played")
    args.select = [c for c in cols if c in m_columns or c in ["*"]] + getattr(args, "select", [])
    if args.action == SC.read and "tags" in m_columns:
        if "duration" in args.select:
            args.select.remove("duration")
        args.select += ["cast(length(tags) / 4.2 / 220 * 60 as INT) + 10 duration"]

    select_sql = "\n        , ".join(args.select)
    return select_sql


def fs_sql(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    m_columns = sql_utils.search_filter(args, m_columns)

    query = f"""
        SELECT
            {media_select_sql(args, m_columns)}
        FROM {args.table} m
        WHERE 1=1
            {" ".join(args.filter_sql)}
            {" ".join(args.aggregate_filter_sql)}
        ORDER BY 1=1
            {', ' + args.sort if args.sort else ''}
        {sql_utils.limit_sql(args)}
    """

    return query, args.filter_bindings


def perf_randomize_using_ids(args, m_columns):
    if args.table == "media" and args.random and not args.print and args.limit in args.defaults:
        limit = 16 * (args.limit or consts.DEFAULT_PLAY_QUEUE)
        where_not_deleted = (
            "where COALESCE(time_deleted,0) = 0"
            if "time_deleted" in m_columns
            and "deleted" not in args.sort_groups_by
            and "time_deleted" not in " ".join(args.where)
            else ""
        )
        args.filter_sql.append(
            f"and m.id in (select id from media {where_not_deleted} order by random() limit {limit})",
        )


def media_sql(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    m_columns = sql_utils.search_filter(args, m_columns)

    perf_randomize_using_ids(args, m_columns)

    select_sql = media_select_sql(args, m_columns)

    query = f"""WITH m as (
            SELECT
                m.id
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , *
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                {" ".join(args.filter_sql)}
            GROUP BY m.id, m.path
        )
        SELECT
            {select_sql}
            , play_count
            , time_first_played
            , time_last_played
            , playhead
        FROM m
        WHERE 1=1
            {" ".join(args.aggregate_filter_sql)}
        ORDER BY 1=1
            {', ' + args.sort if args.sort else ''}
        {sql_utils.limit_sql(args)}
    """

    args.filter_sql = [
        s for s in args.filter_sql if "in (select id from media" not in s
    ]  # only use random id constraint in first query

    return query, args.filter_bindings


def historical_media(args):
    m_columns = args.db["media"].columns_dict
    m_columns = sql_utils.search_filter(args, m_columns)

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , path
                {', title' if 'title' in m_columns else ''}
                {', duration' if 'duration' in m_columns else ''}
                {', subtitle_count' if 'subtitle_count' in m_columns else ''}
            FROM {args.table} m
            JOIN history h on h.media_id = m.id
            WHERE 1=1
            {sql_utils.filter_time_played(args)}
            {'AND COALESCE(time_deleted, 0)=0' if args.hide_deleted else ""}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        WHERE 1=1
            {" ".join([" and " + w for w in args.where])}
            {sql_utils.filter_play_count(args)}
        ORDER BY time_last_played desc {', path' if args.completed else ', playhead desc' }
        LIMIT {args.limit or 5}
    """
    return query, args.filter_bindings


def construct_links_query(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    m_columns = sql_utils.search_filter(args, m_columns)

    args.select = ["path"]
    if args.cols:
        args.select.extend(args.cols)
    for s in ["title", "hostname", "category"]:
        if s in m_columns:
            args.select.append(s)

    query = f"""WITH m as (
            SELECT
                {', '.join(args.select) if args.select else ''}
                , COALESCE(MAX(h.time_played), 0) time_last_played
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , time_deleted
            FROM media m
            LEFT JOIN history h on h.media_id = media.id
            WHERE 1=1
                {" ".join(args.filter_sql)}
            GROUP BY media.id
        )
        SELECT
        {', '.join(args.select) if args.select else ''}
        {", time_last_played" if args.print else ''}
    FROM m
    WHERE 1=1
        {" ".join(args.aggregate_filter_sql)}
    ORDER BY 1=1
        {', ' + args.sort if args.sort else ''}
        , play_count
        {', ROW_NUMBER() OVER ( PARTITION BY hostname )' if 'hostname' in m_columns else ''}
        {', ROW_NUMBER() OVER ( PARTITION BY category )' if 'category' in m_columns else ''}
        , random()
    {sql_utils.limit_sql(args)}
    """

    return query, args.filter_bindings


def construct_tabs_query(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    m_columns = sql_utils.search_filter(args, m_columns)

    query = f"""WITH m as (
            SELECT
                path
                , frequency
                , COALESCE(MAX(h.time_played), 0) time_last_played
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , time_deleted
                , hostname
                , category
            FROM media m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                {" ".join(args.filter_sql)}
            GROUP BY m.id
        )
        SELECT path
        , frequency
        {", time_last_played" if args.print else ''}
        , CASE
            WHEN frequency = 'daily' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Day', '-5 minutes' )) as int)
            WHEN frequency = 'weekly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+7 Days', '-5 minutes' )) as int)
            WHEN frequency = 'monthly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Month', '-5 minutes' )) as int)
            WHEN frequency = 'quarterly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+3 Months', '-5 minutes' )) as int)
            WHEN frequency = 'yearly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Year', '-5 minutes' )) as int)
        END time_valid
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM m
    WHERE 1=1
        {" ".join(args.aggregate_filter_sql)}
        {f"and time_valid < {consts.today_stamp()}" if not args.print else ''}
    ORDER BY 1=1
        {', ' + args.sort if args.sort not in args.defaults else ''}
        {', time_last_played, time_valid, path' if args.print else ''}
        , play_count
        , frequency = 'daily' desc
        , frequency = 'weekly' desc
        , frequency = 'monthly' desc
        , frequency = 'quarterly' desc
        , frequency = 'yearly' desc
        , ROW_NUMBER() OVER ( PARTITION BY
            play_count
            , frequency
            , hostname
            , category
        ) -- prefer to spread hostname, category over time
        , random()
    {sql_utils.limit_sql(args)}
    """

    return query, args.filter_bindings


def construct_captions_search_query(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    c_columns = db_utils.columns(args, "captions")

    m_columns = sql_utils.search_filter(args, m_columns)

    table = "captions"
    cols = args.cols or ["path", "text", "time", "title"]

    is_fts = args.db["captions"].detect_fts()
    if is_fts and args.include:
        table, search_bindings = sql_utils.fts_search_sql(
            "captions",
            fts_table=is_fts,
            include=args.include,
            exclude=args.exclude,
            flexible=args.flexible_search,
        )
        args.filter_bindings = {**args.filter_bindings, **search_bindings}
        c_columns = {**c_columns, "rank": int}
        cols.append("id")
        cols.append("rank")
    else:
        sql_utils.construct_search_bindings(args, ["text"])

    args.select = [c for c in cols if c in {**c_columns, **m_columns, **{"*": "Any"}}]

    select_sql = "\n        , ".join(args.select)
    limit_sql = "LIMIT " + str(args.limit) if args.limit else ""
    query = f"""WITH c as (
        SELECT * FROM {table} m
        WHERE 1=1
            {" ".join(args.filter_sql)}
    )
    SELECT
        {select_sql}
    FROM c
    JOIN media m on m.id = c.media_id
    WHERE 1=1
        {" ".join(args.aggregate_filter_sql)}
    ORDER BY 1=1
        , {args.sort}
    {limit_sql}
    """

    return query, args.filter_bindings


def construct_playlists_query(args) -> tuple[str, dict]:
    pl_columns = db_utils.columns(args, "playlists")

    args.table = "playlists"
    if args.db["playlists"].detect_fts():
        if args.include:
            args.table, search_bindings = sql_utils.fts_search_sql(
                "playlists",
                fts_table=args.db["playlists"].detect_fts(),
                include=args.include,
                exclude=args.exclude,
                flexible=args.flexible_search,
            )
            args.filter_bindings = {**args.filter_bindings, **search_bindings}
        elif args.exclude:
            sql_utils.construct_search_bindings(
                args,
                [k for k in pl_columns if k in db_utils.config["playlists"]["search_columns"] if k in pl_columns],
            )
    else:
        sql_utils.construct_search_bindings(
            args,
            [k for k in pl_columns if k in db_utils.config["playlists"]["search_columns"] if k in pl_columns],
        )

    query = f"""SELECT *
    FROM {args.table} m
    WHERE 1=1
        {" ".join(args.filter_sql)}
        {'AND extractor_key != "Local"' if args.online_media_only else ''}
        {'AND extractor_key = "Local"' if args.local_media_only else ''}
    ORDER BY 1=1
        {', ' + args.playlists_sort if args.playlists_sort else ''}
        , path
        , random()
    {sql_utils.limit_sql(args)}
    """

    return query, args.filter_bindings


def construct_download_query(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    pl_columns = db_utils.columns(args, "playlists")

    m_columns = sql_utils.search_filter(args, m_columns)

    if args.action == SC.download and "time_modified" in m_columns:
        args.filter_sql.append(
            f"""and cast(STRFTIME('%s',
            datetime( COALESCE(m.time_modified,0), 'unixepoch', '+{args.retry_delay}')
            ) as int) < STRFTIME('%s', datetime()) """,
        )

    same_subdomain = """AND m.path like (
        SELECT '%' || SUBSTR(path, INSTR(path, '//') + 2, INSTR( SUBSTR(path, INSTR(path, '//') + 2), '/') - 1) || '%'
        FROM media
        WHERE 1=1
            AND COALESCE(m.time_downloaded,0) = 0
            AND COALESCE(m.time_deleted,0) = 0
        ORDER BY RANDOM()
        LIMIT 1
    )"""
    if "playlists_id" in m_columns:
        query = f"""select
                m.id
                , m.playlists_id
                , m.path
                , p.path playlist_path
                {', m.title' if 'title' in m_columns else ''}
                {', m.duration' if 'duration' in m_columns else ''}
                , m.time_created
                {', m.size' if 'size' in m_columns else ''}
                {', m.time_modified' if 'time_modified' in m_columns else ''}
                {', m.time_downloaded' if 'time_downloaded' in m_columns else ''}
                {', m.time_deleted' if 'time_deleted' in m_columns else ''}
                {', m.error' if 'error' in m_columns and args.verbose >= consts.LOG_DEBUG else ''}
                {', p.extractor_config' if 'extractor_config' in pl_columns else ''}
                , p.extractor_key
            FROM media m
            LEFT JOIN playlists p on p.id = m.playlists_id
            WHERE 1=1
                {'and COALESCE(m.time_downloaded,0) = 0' if 'time_downloaded' in m_columns else ''}
                {'and COALESCE(p.time_deleted, 0) = 0' if 'time_deleted' in pl_columns else ''}
                and m.path like "http%"
                {same_subdomain if getattr(args, 'same_domain', False) else ''}
                {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
                {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
                {" ".join(args.filter_sql)}
            ORDER BY 1=1
                , COALESCE(m.time_modified, 0) = 0 DESC
                {', p.extractor_key IS NOT NULL DESC' if 'sort' in args.defaults else ''}
                {', m.error IS NULL DESC' if 'error' in m_columns else ''}
                {', random()' if 'sort' in args.defaults else ', ' + args.sort}
            {sql_utils.limit_sql(args)}
        """
    else:
        query = f"""select
                m.path
                {', m.title' if 'title' in m_columns else ''}
                {', m.duration' if 'duration' in m_columns else ''}
                {', m.time_created' if 'time_created' in m_columns else ''}
                {', m.size' if 'size' in m_columns else ''}
                {', m.time_modified' if 'time_modified' in m_columns else ''}
                {', m.time_downloaded' if 'time_downloaded' in m_columns else ''}
                {', m.time_deleted' if 'time_deleted' in m_columns else ''}
                {', m.error' if 'error' in m_columns and args.verbose >= consts.LOG_DEBUG else ''}
                , 'Playlist-less media' as extractor_key
            FROM media m
            WHERE 1=1
                {'and COALESCE(m.time_downloaded,0) = 0' if 'time_downloaded' in m_columns else ''}
                {'and COALESCE(m.time_deleted,0) = 0' if 'time_deleted' in m_columns else ''}
                and m.path like "http%"
                {same_subdomain if getattr(args, 'same_domain', '') else ''}
                {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
                {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
                {" ".join(args.filter_sql)}
            ORDER BY 1=1
                , COALESCE(m.time_modified, 0) = 0 DESC
                {', m.error IS NULL DESC' if 'error' in m_columns else ''}
                {', random()' if 'sort' in args.defaults else ', ' + args.sort}
        {sql_utils.limit_sql(args)}
        """

    return query, args.filter_bindings
