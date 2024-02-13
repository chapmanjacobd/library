import argparse, os, sqlite3
from datetime import datetime
from pathlib import Path
from typing import Collection, Dict, List, Optional

from dateutil import parser

from xklb import fs_extract
from xklb.utils import consts, db_utils, iterables, nums, objects, processes, strings
from xklb.utils.consts import DBType
from xklb.utils.log_utils import log


def exists(args, path) -> bool:
    m_columns = db_utils.columns(args, "media")
    try:
        known = args.db.execute(
            f"select 1 from media where path=? or {'webpath' if 'webpath' in m_columns else 'path'}=?",
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
    cv["playlists_id"] = v.pop("playlists_id", None)  # not to be confused with yt-dlp playlist_id
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
    chapters = entry.pop("chapters", None) or []
    entry.pop("description", None)

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
    for chapter in chapters:
        args.db["captions"].insert({"media_id": media_id, **chapter}, alter=True)


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
            check_corrupt=False,
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
    if entry["path"] != webpath and (unrecoverable_error or not error):
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
        {'and COALESCE(time_deleted,0) = 0' if 'time_deleted' in m_columns and "deleted" not in (getattr(args, 'sort_groups_by',None) or '') and "time_deleted" not in args.where else ''}
        {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
        {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
        {'AND COALESCE(time_downloaded,0) = 0' if args.online_media_only and 'time_downloaded' in m_columns else ''}
        {'AND COALESCE(time_downloaded,1)!= 0 AND path not like "http%"' if args.local_media_only and 'time_downloaded' in m_columns else ''}
    """


def get_dir_media(args, dirs: Collection, include_subdirs=False, limit=2_000) -> List[Dict]:
    if len(dirs) == 0:
        return processes.no_media_found()

    m_columns = db_utils.columns(args, "media")

    if include_subdirs:
        filter_paths = "AND (" + " OR ".join([f"path LIKE :subpath{i}" for i in range(len(dirs))]) + ")"
    else:
        filter_paths = (
            "AND ("
            + " OR ".join(
                [f"(path LIKE :subpath{i} and path not like :subpath{i} || '%{os.sep}%')" for i in range(len(dirs))]
            )
            + ")"
        )

    select_sql = "\n        , ".join(s for s in args.select if s not in ["rank"])

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , {select_sql}
                , m.*
            FROM media m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                and m.id in (select id from {args.table})
                {filter_args_sql(args, m_columns)}
                {filter_paths}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        ORDER BY play_count
            , m.path LIKE "http%"
            {'' if 'sort' in args.defaults else ', ' + args.sort}
            , path
        LIMIT {limit}
    """

    subpath_params = {f"subpath{i}": value + "%" for i, value in enumerate(dirs)}

    bindings = {**subpath_params}
    bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("FTS")}}

    media = list(args.db.query(query, bindings))
    log.debug("len(dir_media) = %s", len(media))
    if len(media) == 0:
        log.debug("dir_media dirs %s", dirs)
    else:
        log.debug("get_dir_media[0] %s", media[0:1])

    return media


def get_sibling_media(args, media):
    if args.fetch_siblings in ("always", "all"):
        dirs = set(str(Path(d["path"]).parent) + os.sep for d in media)
        media = get_dir_media(args, dirs)
    elif args.fetch_siblings == "each":
        parents = set(str(Path(d["path"]).parent) + os.sep for d in media)
        media = []
        for parent in parents:
            media.extend(get_dir_media(args, [parent], limit=1)[0:1])
    elif args.fetch_siblings == "if-audiobook":
        new_media = []
        seen = set()
        for d in media:
            if "audiobook" in d["path"].lower():
                parent = str(Path(d["path"]).parent) + os.sep
                if parent not in seen:
                    seen.add(parent)
                    new_media.extend(get_dir_media(args, [parent], limit=1)[0:1])
            else:
                new_media.append(d)
        media = new_media

    # TODO: all-if>10, each-if=10 --lower --upper functionality could be replicated here

    return media


def natsort_media(args, media):
    from natsort import natsorted, ns, os_sorted

    reverse = False
    if args.play_in_order.startswith("reverse_"):
        args.play_in_order = args.play_in_order.replace("reverse_", "", 1)
        reverse = True

    compat = False
    for opt in ("compat_", "nfkd_"):
        if args.play_in_order.startswith(opt):
            args.play_in_order = args.play_in_order.replace(opt, "", 1)
            compat = True

    if "_" in args.play_in_order:
        alg, sort_key = args.play_in_order.split("_", 1)
    else:
        alg, sort_key = args.play_in_order, "ps"

    def func_sort_key(sort_key):
        def fn_key(d):
            if sort_key in ("parent", "stem", "ps", "pts"):
                path = Path(d["path"])

                if sort_key == "parent":
                    return path.parent
                elif sort_key == "stem":
                    return path.stem
                elif sort_key == "ps":
                    return (path.parent, path.stem)
                else:  # sort_key == 'pts'
                    return (path.parent, d["title"], path.stem)
            else:
                return d[sort_key]

        return fn_key

    media_sort_key = func_sort_key(sort_key)

    NS_OPTS = ns.NUMAFTER | ns.NOEXP | ns.NANLAST
    if compat:
        NS_OPTS = NS_OPTS | ns.COMPATIBILITYNORMALIZE | ns.GROUPLETTERS

    if alg == "natural":
        media = natsorted(media, key=media_sort_key, alg=NS_OPTS | ns.DEFAULT, reverse=reverse)
    elif alg in ("nspath", "path"):
        media = natsorted(media, key=media_sort_key, alg=NS_OPTS | ns.PATH, reverse=reverse)
    elif alg == "ignorecase":
        media = natsorted(media, key=media_sort_key, alg=NS_OPTS | ns.IGNORECASE, reverse=reverse)
    elif alg == "lowercase":
        media = natsorted(media, key=media_sort_key, alg=NS_OPTS | ns.LOWERCASEFIRST, reverse=reverse)
    elif alg in ("human", "locale"):
        media = natsorted(media, key=media_sort_key, alg=NS_OPTS | ns.LOCALE, reverse=reverse)
    elif alg == "signed":
        media = natsorted(media, key=media_sort_key, alg=NS_OPTS | ns.REAL, reverse=reverse)
    elif alg == "os":
        media = os_sorted(media, key=media_sort_key, reverse=reverse)
    elif alg == "python":
        media = sorted(media, key=media_sort_key, reverse=reverse)
    else:
        media = natsorted(media, key=func_sort_key(alg), alg=NS_OPTS | ns.DEFAULT, reverse=reverse)

    log.debug("natsort[0] %s", media[0:1])
    return media


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

    select_sql = "\n        , ".join(args.select)
    limit_sql = "LIMIT " + str(args.limit - 1) if args.limit else ""
    offset_sql = f"OFFSET {args.skip}" if args.skip and limit_sql else ""
    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , {select_sql}
                , rank
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                and path != :path
                {filter_args_sql(args, m_columns)}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        WHERE 1=1
            {'' if args.related >= consts.RELATED_NO_FILTER else (" ".join(args.filter_sql) or '')}
        ORDER BY play_count
            , m.path like "http%"
            , {'rank' if 'sort' in args.defaults else f'ntile(1000) over (order by rank)' + (f', {args.sort}' if args.sort else '')}
            , path
        {limit_sql} {offset_sql}
    """

    bindings = {"path": m["path"]}
    if args.related >= consts.RELATED_NO_FILTER:
        bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("FTS")}}
    else:
        bindings = {**bindings, **args.filter_bindings}

    related_media = list(args.db.query(query, bindings))
    log.debug(related_media)
    log.debug("related_media[0] %s", related_media[0:1])

    return [m, *related_media]
