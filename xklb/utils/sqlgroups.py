import sys

from xklb.createdb import gallery_backend, tube_backend
from xklb.utils import consts, db_utils, sql_utils
from xklb.utils.consts import SC, DBType


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


def fs_sql(args, limit) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    args.table, m_columns = sql_utils.search_filter(args, m_columns)

    query = f"""
        SELECT
            {media_select_sql(args, m_columns)}
        FROM {args.table} m
        WHERE 1=1
            {" ".join(args.filter_sql)}
            {" ".join(args.aggregate_filter_sql)}
        ORDER BY 1=1
            {', ' + args.sort if args.sort else ''}
        {sql_utils.limit_sql(limit, args.offset)}
    """

    return query, args.filter_bindings


def perf_randomize_using_ids(args):
    if args.random and not args.include and not args.print and args.limit in args.defaults:
        limit = 16 * (args.limit or consts.DEFAULT_PLAY_QUEUE)
        where_not_deleted = "where COALESCE(time_deleted,0) = 0" if args.hide_deleted else ""
        args.filter_sql.append(
            f"and m.id in (select id from media {where_not_deleted} order by random() limit {limit})",
        )


def media_sql(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    h_columns = db_utils.columns(args, "history")
    args.table, m_columns = sql_utils.search_filter(args, m_columns)

    perf_randomize_using_ids(args)

    select_sql = media_select_sql(args, m_columns)

    query = f"""WITH m as (
            SELECT
                m.id
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                {', FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead' if 'playhead' in h_columns else ''}
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
        {sql_utils.limit_sql(args.limit, args.offset)}
    """

    args.filter_sql = [
        s for s in args.filter_sql if "in (select id from media" not in s
    ]  # only use random id constraint in first query

    return query, args.filter_bindings


def historical_media(args):
    m_columns = args.db["media"].columns_dict
    args.table, m_columns = sql_utils.search_filter(args, m_columns)

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
            {"AND COALESCE(time_deleted, 0)>0" if args.only_deleted else ""}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        WHERE 1=1
            {" ".join([" and " + w for w in args.where])}
            {sql_utils.filter_play_count(args)}
        ORDER BY time_last_played desc {', path' if args.completed else ', playhead desc' }
        {sql_utils.limit_sql(args.limit, args.offset)}
    """
    return query, args.filter_bindings


def construct_links_query(args, limit) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    args.table, m_columns = sql_utils.search_filter(args, m_columns)

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
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                {" ".join(args.filter_sql)}
            GROUP BY m.id
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
    {sql_utils.limit_sql(limit, args.offset)}
    """

    return query, args.filter_bindings


def construct_tabs_query(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    args.table, m_columns = sql_utils.search_filter(args, m_columns)

    query = f"""WITH media_history as (
            SELECT
                path
                , frequency
                , COALESCE(MAX(h.time_played), 0) time_last_played
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , time_deleted
                , hostname
                , category
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                {" ".join(args.filter_sql)}
            GROUP BY m.id
        ), time_valid_tabs as (
            SELECT
                CASE
                    WHEN frequency = 'daily' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Day', '-5 minutes' )) as int)
                    WHEN frequency = 'weekly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+7 Days', '-5 minutes' )) as int)
                    WHEN frequency = 'monthly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Month', '-5 minutes' )) as int)
                    WHEN frequency = 'quarterly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+3 Months', '-5 minutes' )) as int)
                    WHEN frequency = 'yearly' THEN cast(STRFTIME('%s', datetime( time_last_played, 'unixepoch', '+1 Year', '-5 minutes' )) as int)
                END time_valid
                , m.*
                {', ' + ', '.join(args.cols) if args.cols else ''}
            FROM media_history m
            WHERE 1=1
                {" ".join(args.aggregate_filter_sql)}
                {f"and time_valid < {consts.today_stamp()}" if not args.print else ''}
        )
    SELECT
        path
        , frequency
        {", time_last_played" if args.print else ''}
        , time_valid
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM (
        SELECT
            CASE WHEN frequency = 'daily' THEN 1
            ELSE ROW_NUMBER() OVER (
                PARTITION BY hostname, frequency = 'daily'
                ORDER BY 1=1
                    {', time_last_played desc, time_valid desc, path' if args.print else ''}
                    , frequency = 'daily' desc
                    , frequency = 'weekly' desc
                    , frequency = 'monthly' desc
                    , frequency = 'quarterly' desc
                    , frequency = 'yearly' DESC
                    , play_count
                    , time_valid
                    , time_last_played
            )
            END hostname_rank
            , m.*
        FROM time_valid_tabs m
        ) m
    WHERE 1=1
        {'and hostname_rank <= ' + str(args.max_same_domain) if args.max_same_domain else ''}
    ORDER BY 1=1
        {', time_last_played desc, time_valid desc, path' if args.print else ''}
        , frequency = 'daily' desc
        , frequency = 'weekly' desc
        , frequency = 'monthly' desc
        , frequency = 'quarterly' desc
        , frequency = 'yearly' DESC
        , play_count
        , time_valid
        , time_last_played
        {', ' + args.sort if args.sort not in args.defaults else ''}
        , ROW_NUMBER() OVER ( PARTITION BY
            play_count
            , frequency
            , hostname
            , category
        ) -- prefer to spread hostname, category over time
        , random()
    {sql_utils.limit_sql(args.limit, args.offset)}
    """

    return query, args.filter_bindings


def construct_captions_search_query(args) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    c_columns = db_utils.columns(args, "captions")

    m_table, m_columns = sql_utils.search_filter(args, m_columns)

    table = "captions"
    cols = args.cols or ["path", "text", "time", "title"]

    is_fts = args.db["captions"].detect_fts()
    if is_fts and args.search_captions:
        table, search_bindings = sql_utils.fts_search_sql(
            "captions",
            fts_table=is_fts,
            include=args.search_captions,
            exclude=args.exclude,
            flexible=args.flexible_search,
        )
        args.filter_bindings = {**args.filter_bindings, **search_bindings}
        c_columns = {**c_columns, "rank": int}
        cols.append("id")
        cols.append("rank")
        search_sql = []
    else:  # only exclude or no-fts
        search_sql, search_bindings = sql_utils.construct_search_bindings(
            include=args.search_captions,
            exclude=args.exclude,
            columns=["text"],
            exact=args.exact,
            flexible_search=args.flexible_search,
        )
        args.filter_bindings = {**args.filter_bindings, **search_bindings}

    args.select = [c for c in cols if c in {**c_columns, **m_columns, "*": "Any"}]

    select_sql = "\n        , ".join(args.select)
    limit_sql = "LIMIT " + str(args.limit) if args.limit else ""
    query = f"""WITH c as (
        SELECT * FROM {table} m
        WHERE 1=1
            {" ".join(search_sql)}
    )
    SELECT
        {select_sql}
    FROM c
    JOIN {m_table} m on m.id = c.media_id
    WHERE 1=1
        {" ".join(args.aggregate_filter_sql)}
    ORDER BY 1=1
        , {args.sort}
    {limit_sql}
    """

    return query, args.filter_bindings


def construct_playlists_query(args) -> tuple[str, dict]:
    pl_columns = db_utils.columns(args, "playlists")

    pl_table = "playlists"
    if args.db["playlists"].detect_fts() and args.include:
        pl_table, search_bindings = sql_utils.fts_search_sql(
            "playlists",
            fts_table=args.db["playlists"].detect_fts(),
            include=args.include,
            exclude=args.exclude,
            flexible=args.flexible_search,
        )
        args.filter_bindings = {**args.filter_bindings, **search_bindings}
    else:  # only exclude or no-fts
        search_sql, search_bindings = sql_utils.construct_search_bindings(
            include=args.include,
            exclude=args.exclude,
            columns=[k for k in pl_columns if k in db_utils.config["playlists"]["search_columns"] if k in pl_columns],
            exact=args.exact,
            flexible_search=args.flexible_search,
        )
        args.filter_sql.extend(search_sql)
        args.filter_bindings = {**args.filter_bindings, **search_bindings}

    query = f"""SELECT *
    FROM {pl_table} m
    WHERE 1=1
        {" ".join(args.filter_sql)}
        {'AND extractor_key != "Local"' if args.online_media_only else ''}
        {'AND extractor_key = "Local"' if args.local_media_only else ''}
    ORDER BY 1=1
        {', ' + args.playlists_sort if args.playlists_sort else ''}
        , path
        , random()
    {sql_utils.limit_sql(args.limit, args.offset)}
    """

    return query, args.filter_bindings


def construct_download_query(args, dl_status=False) -> tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    pl_columns = db_utils.columns(args, "playlists")

    args.table, m_columns = sql_utils.search_filter(args, m_columns)
    if args.safe:
        if args.profile in (DBType.audio, DBType.video):
            is_supported = tube_backend.is_supported
        elif args.profile in (DBType.image,):
            is_supported = gallery_backend.is_supported
        else:
            raise NotImplementedError

        args.db.register_function(is_supported, deterministic=True)

    if "time_modified" in m_columns and not dl_status:
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

    is_media_playlist = "playlists_id" in m_columns and "id" in pl_columns
    query = f"""select
            m.id
            {', m.playlists_id' if "playlists_id" in m_columns else ''}
            , m.path
            {', p.path playlist_path' if is_media_playlist else ''}
            {', m.category' if 'category' in m_columns else ''}
            {', m.title' if 'title' in m_columns else ''}
            {', m.duration' if 'duration' in m_columns else ''}
            , m.time_created
            {', m.size' if 'size' in m_columns else ''}
            {', m.time_modified' if 'time_modified' in m_columns else ''}
            {', m.download_attempts' if 'download_attempts' in m_columns else ''}
            {', m.time_downloaded' if 'time_downloaded' in m_columns else ''}
            {', m.time_deleted' if 'time_deleted' in m_columns else ''}
            {', m.error' if 'error' in m_columns and args.verbose >= consts.LOG_DEBUG else ''}
            {', p.extractor_config' if is_media_playlist and 'extractor_config' in pl_columns else ''}
            {', p.extractor_key' if is_media_playlist and 'extractor_key' in pl_columns else ", 'Playlist-less media' as extractor_key"}
        FROM {args.table} m
        {'LEFT JOIN playlists p on p.id = m.playlists_id' if is_media_playlist else ''}
        WHERE 1=1
            {'and COALESCE(m.time_downloaded,0) = 0' if 'time_downloaded' in m_columns and not dl_status else ''}
            {f'and COALESCE(m.download_attempts,0) <= {args.download_retries}' if 'download_attempts' in m_columns and not dl_status else ''}
            {'and COALESCE(p.time_deleted, 0) = 0' if is_media_playlist and 'time_deleted' in pl_columns and not "time_deleted" in " ".join(args.filter_sql) else ''}
            {'and m.path like "http%"' if not dl_status else ''}
            {same_subdomain if getattr(args, 'same_domain', False) else ''}
            {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
            {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
            {'AND is_supported(path)' if args.safe else ''}
            {" ".join(args.filter_sql)}
        ORDER BY 1=1
            {', COALESCE(m.time_modified, 0) = 0 DESC' if 'time_modified' in m_columns else ''}
            {', m.error IS NULL DESC' if 'error' in m_columns else ''}
            {', ' + args.sort if 'sort' not in args.defaults else ''}
            {', p.extractor_key IS NOT NULL DESC' if is_media_playlist and 'extractor_key' in pl_columns and 'sort' in args.defaults else ''}
            , random()
        {sql_utils.limit_sql(args.limit, args.offset)}
    """

    return query, args.filter_bindings
