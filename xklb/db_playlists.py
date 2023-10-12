import sqlite3
from datetime import datetime
from typing import List, Optional

from xklb import db
from xklb.utils import consts, iterables, nums, objects
from xklb.utils.log_utils import log

"""
playlists table
    extractor_key = Name of the Extractor -- "Local", "Imgur", "YouTube"
    extractor_playlist_id = ID that the extractor uses to refer to playlists

media table
    extractor_id = ID that the Extractor uses to refer to media
    playlist_id = Foreign key to playlists table
"""


def consolidate(args, v: dict) -> dict:
    release_date = v.pop("release_date", None)
    upload_date = v.pop("upload_date", None) or release_date
    if upload_date:
        try:
            upload_date = nums.to_timestamp(datetime.strptime(upload_date, "%Y%m%d"))
        except Exception:
            upload_date = None

    cv = {}
    cv["time_uploaded"] = upload_date
    cv["time_modified"] = consts.now()
    cv["time_deleted"] = 0

    cv["extractor_config"] = {
        **(v.pop("extractor_config", None) or {}),
        **(getattr(args, "extractor_config", None) or {}),
    }

    cv["extractor_key"] = iterables.safe_unpack(
        v.pop("ie_key", None), v.pop("extractor_key", None), v.pop("extractor", None)
    )
    cv["extractor_playlist_id"] = iterables.safe_unpack(v.pop("playlist_id", None), v.pop("id", None))
    cv["title"] = iterables.safe_unpack(v.get("playlist_title"), v.pop("title", None))

    cv["uploader"] = iterables.safe_unpack(
        v.pop("playlist_uploader_id", None),
        v.pop("playlist_uploader", None),
        v.pop("channel_id", None),
        v.pop("uploader_url", None),
        v.pop("channel_url", None),
        v.pop("uploader", None),
        v.pop("channel", None),
        v.pop("uploader_id", None),
    )

    v = {
        k: v
        for k, v in v.items()
        if not (k.startswith("_") or k in consts.MEDIA_KNOWN_KEYS + consts.PLAYLIST_KNOWN_KEYS or v is None)
    }
    if v != {}:
        log.info("Extra playlists data %s", v)
        # breakpoint()

    return objects.dict_filter_bool(cv) or {}


def get_id(args, playlist_path) -> int:
    return args.db.pop("select id from playlists where path=?", [str(playlist_path)])


def _add(args, entry):
    playlists_id = get_id(args, entry["path"])
    if playlists_id:
        entry["id"] = playlists_id
        args.db["playlists"].upsert(entry, pk="id", alter=True)
    else:
        entry["time_created"] = consts.APPLICATION_START
        entry["hours_update_delay"] = 70  # about three days
        args.db["playlists"].insert(entry, pk="id", alter=True)
        playlists_id = get_id(args, entry["path"])
    return playlists_id


def exists(args, playlist_path) -> bool:
    try:
        known = args.db.pop("select 1 from playlists where path=?", [str(playlist_path)])
    except sqlite3.OperationalError as e:
        log.debug(e)
        return False
    if known is None:
        return False
    return True


def get_subpath_playlist_id(args, playlist_path) -> Optional[int]:
    try:
        known = args.db.pop(
            "select path from playlists where ? like path || '%' and path != ?",
            [str(playlist_path), str(playlist_path)],
        )
    except sqlite3.OperationalError as e:
        log.debug(e)
        return None
    return known


def add(args, playlist_path: str, info: dict, check_subpath=False, extractor_key=None) -> int:
    if check_subpath:
        subpath_playlist_id = get_subpath_playlist_id(args, playlist_path)
        if subpath_playlist_id:
            return subpath_playlist_id

    pl = consolidate(args, objects.dumbcopy(info))
    playlist = {**pl, "path": playlist_path, **args.extra_playlist_data}
    if extractor_key:
        playlist["extractor_key"] = extractor_key
    return _add(args, objects.dict_filter_bool(playlist))


def media_exists(args, playlist_path, path) -> bool:
    m_columns = db.columns(args, "media")
    try:
        known = args.db.execute(
            f"select 1 from media where playlist_id in (select id from playlists where path = ?) and (path=? or {'web' if 'webpath' in m_columns else ''}path=?)",
            [str(playlist_path), str(path), str(path)],
        ).fetchone()
    except sqlite3.OperationalError as e:
        log.debug(e)
        return False
    if known is None:
        return False
    return True


def decrease_update_delay(args, playlist_path: str) -> None:
    if "playlists" not in args.db.table_names():
        return

    try:
        with args.db.conn:
            args.db.conn.execute(
                """
                UPDATE playlists
                SET time_modified = cast(STRFTIME('%s', 'now') as int)
                , hours_update_delay = CASE
                    WHEN 0.5 * hours_update_delay <= 0 THEN 1
                    WHEN 0.5 * hours_update_delay >= 8760 THEN 8760
                    ELSE 0.5 * hours_update_delay
                END
                WHERE hours_update_delay IS NOT NULL
                    AND path = ?
                """,
                [playlist_path],
            )
    except sqlite3.OperationalError:
        with args.db.conn:
            args.db.conn.execute("ALTER TABLE playlists ADD COLUMN hours_update_delay INTEGER DEFAULT 70")


def increase_update_delay(args, playlist_path: str) -> None:
    if "playlists" not in args.db.table_names():
        return

    try:
        with args.db.conn:
            args.db.conn.execute(
                """
                UPDATE playlists
                SET time_modified = cast(STRFTIME('%s', 'now') as int)
                ,   hours_update_delay = CASE
                    WHEN 2 * hours_update_delay <= 0 THEN 1
                    WHEN 2 * hours_update_delay >= 8760 THEN 8760
                    ELSE 2 * hours_update_delay
                END
                WHERE hours_update_delay IS NOT NULL
                    AND path = ?
                """,
                [playlist_path],
            )
    except sqlite3.OperationalError:
        with args.db.conn:
            args.db.conn.execute("ALTER TABLE playlists ADD COLUMN IF NOT EXISTS hours_update_delay INTEGER DEFAULT 70")


def get_all(args, cols="path, extractor_config", sql_filters=None) -> List[dict]:
    pl_columns = db.columns(args, "playlists")
    if sql_filters is None:
        sql_filters = []
    if "time_deleted" in pl_columns:
        sql_filters.append("AND COALESCE(time_deleted,0) = 0")
    if "hours_update_delay" in pl_columns and not args.force:
        sql_filters.append("AND (cast(STRFTIME('%s', 'now') as int) - time_modified) >= (hours_update_delay * 60 * 60)")

    try:
        known_playlists = list(
            args.db.query(f"select {cols} from playlists where 1=1 {' '.join(sql_filters)} order by random()"),
        )
    except sqlite3.OperationalError:
        known_playlists = []
    return known_playlists


def log_problem(args, playlist_path) -> None:
    if exists(args, playlist_path):
        log.warning("Start of known playlist reached %s", playlist_path)
    else:
        log.warning("Could not add playlist %s", playlist_path)


def save_undownloadable(args, playlist_path, extractor) -> None:
    entry = {
        "path": playlist_path,
        "title": f"No data from {extractor} extractor",
        "extractor_config": args.extractor_config,
        **args.extra_playlist_data,
    }
    _add(args, objects.dict_filter_bool(entry))
