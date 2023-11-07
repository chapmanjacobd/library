import argparse, os, sqlite3, sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dateutil import parser

from xklb import fs_extract
from xklb.utils import consts, db_utils, iterables, nums, objects, processes, strings
from xklb.utils.consts import DBType
from xklb.utils.log_utils import log


def exists(args, path) -> bool:
    m_columns = db_utils.columns(args, "media")
    try:
        known = args.db.execute(
            f"select 1 from media where path=? or {'web' if 'webpath' in m_columns else ''}path=?",
            [str(path), str(path)],
        ).fetchone()
    except sqlite3.OperationalError as e:
        log.debug(e)
        return False
    if known is None:
        return False
    return True


def get(args, path):
    return args.db.pop_dict("select * from media where path = ?", [path])


def get_paths(args):
    tables = args.db.table_names()

    known_playlists = set()
    if "media" in tables:
        known_playlists.update(d["path"] for d in args.db.query("SELECT path from media"))

        m_columns = db_utils.columns(args, "media")
        if "webpath" in m_columns:
            known_playlists.update(d["webpath"] for d in args.db.query("SELECT webpath from media"))

    if "playlists" in tables:
        known_playlists.update(d["path"] for d in args.db.query("SELECT path from playlists"))

    return known_playlists


def consolidate(v: dict) -> Optional[dict]:
    if v.get("title") in ("[Deleted video]", "[Private video]"):
        return None

    v = objects.flatten_dict(v, passthrough_keys=["automatic_captions", "http_headers", "subtitles"])

    upload_date = iterables.safe_unpack(
        v.pop("upload_date", None),
        v.pop("release_date", None),
        v.pop("date", None),
        v.pop("created_at", None),
        v.pop("published", None),
        v.pop("updated", None),
    )
    if upload_date:
        if isinstance(upload_date, datetime):
            upload_date = nums.to_timestamp(upload_date)
        else:
            try:
                upload_date = nums.to_timestamp(parser.parse(upload_date))
            except Exception:
                upload_date = None

    cv = {}
    cv["playlist_id"] = v.pop("playlist_id", None)
    cv["webpath"] = iterables.safe_unpack(
        v.pop("webpath", None),
        v.pop("webpage_url", None),
        v.pop("url", None),
        v.pop("original_url", None),
        v.pop("post_url", None),
        v.pop("image_permalink", None),
    )
    cv["path"] = iterables.safe_unpack(v.pop("path", None), v.pop("local_path", None), cv["webpath"])
    size_bytes = iterables.safe_unpack(v.pop("filesize_approx", None), v.pop("size", None))
    cv["size"] = 0 if not size_bytes else int(size_bytes)
    duration = v.pop("duration", None)
    cv["duration"] = 0 if not duration else int(duration)
    cv["time_uploaded"] = upload_date
    cv["time_created"] = consts.now()
    cv["time_modified"] = 0  # this should be 0 if the file has never been downloaded
    cv["time_deleted"] = 0
    cv["time_downloaded"] = 0
    language = v.pop("language", None)
    cv["tags"] = strings.combine(
        "language:" + language if language else None,
        v.pop("description", None),
        v.pop("caption", None),
        v.pop("content", None),
        v.pop("categories", None),
        v.pop("genre", None),
        v.pop("tags", None),
        v.pop("labels", None),
    )

    cv["latitude"] = iterables.safe_unpack(
        v.pop("latitude", None),
        v.pop("lat", None),
    )
    cv["longitude"] = iterables.safe_unpack(
        v.pop("longitude", None),
        v.pop("long", None),
        v.pop("lng", None),
    )

    # extractor_key should only be in playlist table
    cv["extractor_id"] = v.pop("id", None)
    cv["title"] = iterables.safe_unpack(v.pop("title", None), v.get("playlist_title"))
    cv["width"] = v.pop("width", None)
    cv["height"] = v.pop("height", None)
    fps = v.pop("fps", None)
    cv["fps"] = 0 if not fps else int(fps)
    cv["live_status"] = v.pop("live_status", None)
    cv["age_limit"] = iterables.safe_unpack(
        v.pop("age_limit", None),
        18 if v.pop("is_mature", None) or v.pop("is_nsfw", None) else 0,
    )

    account = v.pop("account", None) or {}
    cv["uploader"] = iterables.safe_unpack(
        v.pop("channel_id", None),
        v.pop("uploader_url", None),
        v.pop("channel_url", None),
        v.pop("uploader", None),
        v.pop("channel", None),
        v.pop("uploader_id", None),
        account.pop("username", None),
        v.pop("account_id", None),
        account.pop("id", None),
        v.pop("name", None),
        v.pop("author", None),
        v.pop("post_author", None),
        v.pop("blog_name", None),
        v.pop("uuid", None),
        v.pop("playlist_uploader_id", None),
        v.pop("playlist_uploader", None),
    )

    cv["view_count"] = iterables.safe_unpack(
        v.pop("view_count", None),
    )
    cv["num_comments"] = iterables.safe_unpack(
        v.pop("replies", None),
    )
    cv["favorite_count"] = iterables.safe_sum(
        v.pop("favorite_count", None),
        v.pop("likes", None),
        v.pop("note_count", None),
        v.pop("point_count", None),
    )
    cv["score"] = iterables.safe_unpack(v.pop("score", None))
    cv["upvote_ratio"] = v.pop("average_rating", None)
    if v.get("upvote_count") and v.get("upvote_count"):
        upvote_count = v.pop("upvote_count")
        downvote_count = v.pop("downvote_count")
        cv["upvote_ratio"] = upvote_count / (upvote_count + downvote_count)

    v = {
        k: v
        for k, v in v.items()
        if not (k.startswith(("_", "reblogged_")) or k in consts.MEDIA_KNOWN_KEYS or v is None)
    }
    if v != {}:
        log.info("Extra media data %s", v)
        # breakpoint()

    return objects.dict_filter_bool(cv)


def add(args, entry):
    if "path" not in entry:
        entry["path"] = entry.get("webpath")
    if not entry.get("path"):
        log.warning('Skipping insert: no "path" in entry %s', entry)
        return

    tags = entry.pop("tags", None) or ""

    media_id = args.db.pop("select id from media where path = ?", [entry["path"]])
    try:
        if media_id:
            entry["id"] = media_id

            args.db["media"].upsert(objects.dict_filter_bool(entry), pk="id", alter=True)
        else:
            args.db["media"].insert(objects.dict_filter_bool(entry), pk="id", alter=True)
            media_id = args.db.pop("select id from media where path = ?", [entry["path"]])
    except sqlite3.IntegrityError:
        log.error("media_id %s: %s", media_id, entry)
        raise
    if tags:
        args.db["captions"].insert({"media_id": media_id, "time": 0, "text": tags}, alter=True)


def playlist_media_add(
    args,
    webpath: str,
    info: Optional[dict] = None,
    error=None,
    unrecoverable_error=False,
) -> None:
    if not info:
        info = {"path": webpath}

    consolidated_entry = consolidate(info) or {}

    entry = {
        **consolidated_entry,
        "time_deleted": consts.APPLICATION_START if unrecoverable_error else 0,
        "webpath": webpath,
        "error": error,
    }
    add(args, entry)


def download_add(
    args,
    webpath: str,
    info: Optional[dict] = None,
    local_path=None,
    error=None,
    unrecoverable_error=False,
) -> None:
    if local_path and Path(local_path).exists():
        local_path = str(Path(local_path).resolve())
        fs_args = argparse.Namespace(
            profile=args.profile,
            scan_subtitles=args.profile == DBType.video,
            ocr=False,
            speech_recognition=False,
            delete_unplayable=False,
            check_corrupt=0.0,
            delete_corrupt=None,
        )
        fs_tags = objects.dict_filter_bool(fs_extract.extract_metadata(fs_args, local_path), keep_0=False) or {}
        fs_extract.clean_up_temp_dirs()
    else:
        fs_tags = {"time_modified": consts.now()}

    if not info:  # not downloaded or already downloaded
        info = {"path": webpath}

    consolidated_entry = consolidate(info) or {}

    entry = {
        **consolidated_entry,
        "time_deleted": consts.APPLICATION_START if unrecoverable_error else 0,
        **fs_tags,
        "webpath": webpath,
        "error": error,
    }
    add(args, entry)
    if entry["path"] != webpath:
        with args.db.conn:
            args.db.conn.execute("DELETE from media WHERE path = ?", [webpath])


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


def get_related_media(args, m: Dict) -> List[Dict]:
    m_columns = db_utils.columns(args, "media")
    m_columns.update(rank=int)

    m = get(args, m["path"])
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
