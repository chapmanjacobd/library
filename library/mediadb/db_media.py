import argparse, os, re, sqlite3
from collections import Counter
from collections.abc import Collection
from pathlib import Path

from library.createdb import fs_add_metadata
from library.createdb.subtitle import clean_up_temp_dirs
from library.utils import consts, date_utils, db_utils, iterables, log_utils, objects, processes, sql_utils, strings
from library.utils.consts import DBType
from library.utils.log_utils import log


def create(args):
    args.db.execute(
        """
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlists_id INTEGER,
            time_created INTEGER DEFAULT (strftime('%s', 'now')),
            time_modified INTEGER,
            time_deleted INTEGER,
            time_uploaded INTEGER,
            time_downloaded INTEGER,
            size INTEGER,
            duration INTEGER,
            float REAL,
            path TEXT NOT NULL
        );
        """
    )
    args.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS media_uniq_path_idx ON media (playlists_id, path);")


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


def consolidate(v: dict) -> dict | None:
    if v.get("title") in ("[Deleted video]", "[Private video]"):
        return None

    v = objects.flatten_dict(v, passthrough_keys=["automatic_captions", "http_headers", "subtitles"])

    upload_time = date_utils.tube_date(v)

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
    cv["time_uploaded"] = upload_time
    cv["time_created"] = iterables.safe_unpack(v.pop("time_created", None), consts.now())
    cv["time_modified"] = 0  # this should be 0 if the file has never been downloaded
    cv["time_deleted"] = 0
    cv["time_downloaded"] = 0
    cv["language"] = iterables.safe_unpack(
        v.pop("language", None),
        v.pop("lang_code", None),
    )
    cv["tags"] = strings.combine(
        v.pop("description", None),
        v.pop("caption", None),
        v.pop("content", None),
        v.pop("categories", None),
        v.pop("catname", None),
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
    cv["extractor_id"] = iterables.safe_unpack(v.pop("extractor_id", None), v.pop("id", None))
    cv["title"] = iterables.safe_unpack(v.pop("title", None), v.get("playlist_title"))
    cv["width"] = v.pop("width", None)
    cv["height"] = v.pop("height", None)
    cv["fps"] = v.pop("fps", None) or 0.0
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
        v.pop("author_info", None),
        v.pop("post_author", None),
        v.pop("blog_name", None),
        v.pop("uuid", None),
        v.pop("playlist_uploader_id", None),
        v.pop("playlist_uploader", None),
        v.pop("playlist_channel_id", None),
        v.pop("playlist_channel", None),
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
        log.debug("Extra media data %s", v)
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
    subtitles = entry.pop("subtitles", None) or []
    entry.pop("description", None)
    entry = objects.dict_filter_bool(entry)
    if entry is None:
        return

    with args.db.conn:
        existing_record = args.db.pop_dict("select * from media where path = ?", [entry["path"]])
        if not existing_record and "webpath" in entry and not entry.get("error"):
            existing_record = args.db.pop_dict(
                "select * from media where path = ?", [entry["webpath"]]
            )  # replace remote with local
        media_id = None
        if existing_record:
            media_id = existing_record["id"]
            entry = existing_record | entry
            if existing_record.get("time_created"):
                entry["time_created"] = existing_record["time_created"]
        if "download_attempts" in entry:
            attempts = entry["download_attempts"] or 0
            if existing_record and "download_attempts" in existing_record:
                attempts = max(attempts or 0, existing_record["download_attempts"] or 0)
            entry["download_attempts"] = min(consts.SQLITE_INT2, attempts + 1)
        try:
            args.db["media"].insert(entry, pk=["playlists_id", "path"], alter=True, replace=True)
        except sqlite3.IntegrityError:
            log.error("media_id %s: %s", media_id, entry)
            raise
    if media_id is None:
        media_id = args.db.pop("select id from media where path = ?", [entry["path"]])

    if tags:
        args.db["captions"].insert({"media_id": media_id, "time": 0, "text": tags}, alter=True)
    for chapter in chapters:
        args.db["captions"].insert({"media_id": media_id, **chapter}, alter=True)
    if len(subtitles) > 0:
        args.db["captions"].insert_all([{**d, "media_id": media_id} for d in subtitles], alter=True)


def mark_media_undeleted(args, paths) -> int:
    paths = iterables.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = iterables.chunks(paths, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    """update media
                    set time_deleted=0
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


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


def update_media(args, media, mark_deleted=True):
    t = log_utils.Timer()
    scanned_set = {d["path"] for d in media}

    try:
        deleted_set = {d["path"] for d in args.db.query("select path from media where time_deleted > 0")}
    except Exception as e:
        log.debug(e)
    else:
        undeleted_files = list(deleted_set.intersection(scanned_set))
        undeleted_count = mark_media_undeleted(args, undeleted_files)
        if undeleted_count > 0:
            print("Marking", undeleted_count, "metadata records as undeleted")
    log.debug("undelete: %s", t.elapsed())

    try:
        existing_set = {d["path"] for d in args.db.query("select path from media WHERE coalesce(time_deleted, 0) = 0")}
    except Exception as e:
        log.debug(e)
        new_files = scanned_set
    else:
        new_files = scanned_set - existing_set

        if mark_deleted:
            deleted_files = list(existing_set - scanned_set)
            if not scanned_set and len(deleted_files) >= len(existing_set) and not args.force:
                print("No media scanned.")
                return []
            deleted_count = mark_media_deleted(args, deleted_files)
            if deleted_count > 0:
                print("Marking", deleted_count, "orphaned metadata records as deleted")
            log.debug("mark_deleted: %s", t.elapsed())

    new_media = [d for d in media if d["path"] in new_files]
    args.db["media"].insert_all(new_media, pk=["playlists_id", "path"], alter=True, replace=True)
    return None


def playlist_media_add(
    args,
    webpath: str,
    info: dict | None = None,
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
    info: dict | None = None,
    local_path=None,
    error=None,
    mark_deleted=False,
    delete_webpath_entry=None,
) -> None:
    if delete_webpath_entry is None:
        delete_webpath_entry = mark_deleted or not error

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
        fs_tags = fs_add_metadata.extract_metadata(fs_args, local_path)
        fs_tags = objects.dict_filter_bool(fs_tags, keep_0=False) or {}
        clean_up_temp_dirs()
    else:
        fs_tags = {"time_modified": consts.now()}

    if not info:  # not downloaded or already downloaded
        info = {"path": webpath}

    consolidated_entry = consolidate(info) or {}

    entry = {
        **consolidated_entry,
        "time_deleted": consts.APPLICATION_START if mark_deleted else 0,
        **fs_tags,
        "webpath": webpath,
        "error": error,
        "time_modified": consts.now(),
        "download_attempts": info.get("download_attempts") or 0,
    }
    add(args, entry)

    if delete_webpath_entry and entry["path"] != webpath:
        with args.db.conn:
            args.db.conn.execute("DELETE from media WHERE path = ?", [webpath])


def natsort_media(args, media):
    from natsort import natsorted, ns, os_sorted

    config = args.play_in_order

    reverse = False
    if config.startswith("reverse_"):
        config = config.replace("reverse_", "", 1)
        reverse = True

    compat = False
    for opt in ("compat_", "nfkd_"):
        if config.startswith(opt):
            config = config.replace(opt, "", 1)
            compat = True

    if "_" in config:
        alg, sort_key = config.split("_", 1)
    else:
        alg, sort_key = config, "ps"

    def func_sort_key(sort_key):
        ignore_pattern = re.compile(r"\d{3,4}[pi]")  # ignore 720p, 1080i, etc

        @strings.output_filter(ignore_pattern)
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


def get_dir_media(args, dirs: Collection, include_subdirs=False, limit=2_000) -> list[dict]:
    if len(dirs) == 0:
        return processes.no_media_found()

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

    select_sql = "\n        , ".join(s for s in args.select)

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , *
                {', rank' if 'rank' in select_sql else ''}
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.rowid
            WHERE 1=1
                and m.rowid in (select rowid as id from {args.table})
                {filter_paths}
                {" ".join(args.filter_sql)}
            GROUP BY m.rowid, m.path
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
        ORDER BY play_count
            , m.path LIKE "http%"
            , path
            {'' if 'sort' in args.defaults else ', ' + args.sort}
        LIMIT {limit}
    """

    subpath_params = {f"subpath{i}": value + "%" for i, value in enumerate(dirs)}

    bindings = {**subpath_params}
    bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("S_")}}

    media = list(args.db.query(query, bindings))
    log.debug("len(dir_media) = %s", len(media))
    if len(media) == 0:
        log.debug("dir_media dirs %s", dirs)
    else:
        log.debug("get_dir_media[0] %s", media[0:1])

    return media


def get_playlist_media(args, playlist_paths) -> list[dict]:
    select_sql = "\n        , ".join(s for s in args.select)

    playlists_subquery = (
        """AND playlists_id in (
        SELECT rowid as id from playlists
        WHERE path IN ("""
        + ",".join(f":playlist{i}" for i, _ in enumerate(playlist_paths))
        + "))"
    )
    playlists_params = {f"playlist{i}": str(Path(p).resolve()) for i, p in enumerate(playlist_paths)}

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , *
                {', rank' if 'rank' in select_sql else ''}
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.rowid
            WHERE 1=1
                and m.rowid in (select rowid as id from {args.table})
                {playlists_subquery}
                {" ".join(args.filter_sql)}
            GROUP BY m.rowid, m.path
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
        ORDER BY play_count
            , path
            {'' if 'sort' in args.defaults else ', ' + args.sort}
        {sql_utils.limit_sql(args.limit, args.offset)}
    """

    bindings = {**playlists_params}
    bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("S_")}}

    media = list(args.db.query(query, bindings))
    log.debug("len(playlist_media) = %s", len(media))

    return media


def get_next_dir_media(args, folder, limit=1):
    if args.play_in_order:
        media = get_dir_media(args, [folder], limit=limit * 100)
        media = natsort_media(args, media)
        m = media[0:limit]
    else:
        m = get_dir_media(args, [folder], limit=limit)[0:limit]
    return m


def get_sibling_media(args, media):
    if args.fetch_siblings in ("all", "always"):
        dirs = {str(Path(d["path"]).parent) + os.sep for d in media}
        media = get_dir_media(args, dirs)

    elif args.fetch_siblings == "each":
        parent_counts = Counter(str(Path(d["path"]).parent) + os.sep for d in media)
        media = []
        for parent, count in parent_counts.items():
            media.extend(
                get_next_dir_media(
                    args, parent, limit=min(args.fetch_siblings_max, count) if args.fetch_siblings_max > 0 else count
                )
            )

    elif args.fetch_siblings == "if-first":
        original_paths = {d["path"] for d in media}
        parents = {str(Path(d["path"]).parent) + os.sep for d in media}
        media = []
        for parent in parents:
            next_media = get_next_dir_media(args, parent)[0]
            if next_media["path"] in original_paths:
                media.append(next_media)

    elif args.fetch_siblings == "if-audiobook":
        new_media = []
        seen_parents = {}
        for d in media:
            if "audiobook" in d["path"].lower():
                parent = str(Path(d["path"]).parent) + os.sep
                if parent not in seen_parents:
                    seen_parents[parent] = sum(1 for m in media if str(Path(m["path"]).parent) + os.sep == parent)
                    count = seen_parents[parent]
                    new_media.extend(
                        get_next_dir_media(
                            args,
                            parent,
                            limit=min(args.fetch_siblings_max, count) if args.fetch_siblings_max > 0 else count,
                        )
                    )
            else:
                new_media.append(d)
        media = new_media

    elif args.fetch_siblings.isdigit():
        parents = {str(Path(d["path"]).parent) + os.sep for d in media}
        media = []
        for parent in parents:
            media.extend(get_next_dir_media(args, parent, limit=int(args.fetch_siblings)))

    return media


def get_related_media(args, m: dict) -> list[dict]:
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
    args.table, search_bindings = sql_utils.fts_search_sql(
        "media",
        fts_table=args.db["media"].detect_fts(),
        include=args.include,
        exclude=args.exclude,
        flexible=True,
    )
    args.filter_bindings = {**args.filter_bindings, **search_bindings}

    select_sql = "\n        , ".join(s for s in args.select)

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , *
                {', rank' if 'rank' in select_sql else ''}
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.rowid
            WHERE 1=1
                and path != :path
                {'' if args.related >= consts.RELATED_NO_FILTER else " ".join(args.filter_sql)}
            GROUP BY m.rowid, m.path
        )
        SELECT
            {select_sql}
            , play_count
            , time_first_played
            , time_last_played
            , playhead
        FROM m
        WHERE 1=1
            {'' if args.related >= consts.RELATED_NO_FILTER else " ".join(args.aggregate_filter_sql)}
        ORDER BY play_count
            , m.path like "http%"
            , {'rank' if 'sort' in args.defaults else 'ntile(1000) over (order by rank)' + (f', {args.sort}' if args.sort else '')}
            , path
        {sql_utils.limit_sql(args.limit, args.offset, limit_adj=-1)}
    """

    bindings = {"path": m["path"]}
    if args.related >= consts.RELATED_NO_FILTER:
        bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("S_")}}
    else:
        bindings = {**bindings, **args.filter_bindings}

    related_media = list(args.db.query(query, bindings))
    log.debug(related_media)
    log.debug("related_media[0] %s", related_media[0:1])

    return [m, *related_media]
