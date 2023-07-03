import argparse, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dateutil import parser

from xklb import consts, db, fs_extract, utils
from xklb.consts import DBType
from xklb.utils import combine, log, safe_unpack


def exists(args, path) -> bool:
    m_columns = db.columns(args, "media")
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

        m_columns = db.columns(args, "media")
        if "webpath" in m_columns:
            known_playlists.update(d["webpath"] for d in args.db.query("SELECT webpath from media"))

    if "playlists" in tables:
        known_playlists.update(d["path"] for d in args.db.query("SELECT path from playlists"))

    return known_playlists


def consolidate(v: dict) -> Optional[dict]:
    if v.get("title") in ("[Deleted video]", "[Private video]"):
        return None

    v = utils.flatten_dict(v, passthrough_keys=["automatic_captions", "http_headers", "subtitles"])

    upload_date = safe_unpack(
        v.pop("upload_date", None),
        v.pop("release_date", None),
        v.pop("date", None),
        v.pop("created_at", None),
        v.pop("published", None),
        v.pop("updated", None),
    )
    if upload_date:
        if isinstance(upload_date, datetime):
            upload_date = int(upload_date.replace(tzinfo=timezone.utc).timestamp())
        else:
            try:
                upload_date = int(parser.parse(upload_date).replace(tzinfo=timezone.utc).timestamp())
            except Exception:
                upload_date = None

    cv = {}
    cv["playlist_id"] = v.pop("playlist_id", None)
    cv["webpath"] = safe_unpack(
        v.pop("webpath", None),
        v.pop("webpage_url", None),
        v.pop("url", None),
        v.pop("original_url", None),
        v.pop("post_url", None),
        v.pop("image_permalink", None),
    )
    cv["path"] = safe_unpack(v.pop("path", None), v.pop("local_path", None), cv["webpath"])
    size_bytes = safe_unpack(v.pop("filesize_approx", None), v.pop("size", None))
    cv["size"] = 0 if not size_bytes else int(size_bytes)
    duration = v.pop("duration", None)
    cv["duration"] = 0 if not duration else int(duration)
    cv["time_uploaded"] = upload_date
    cv["time_created"] = consts.now()
    cv["time_modified"] = 0  # this should be 0 if the file has never been downloaded
    cv["time_deleted"] = 0
    cv["time_downloaded"] = 0
    language = v.pop("language", None)
    cv["tags"] = combine(
        "language:" + language if language else None,
        v.pop("description", None),
        v.pop("caption", None),
        v.pop("content", None),
        v.pop("categories", None),
        v.pop("genre", None),
        v.pop("tags", None),
        v.pop("labels", None),
    )

    cv["latitude"] = safe_unpack(
        v.pop("latitude", None),
        v.pop("lat", None),
    )
    cv["longitude"] = safe_unpack(
        v.pop("longitude", None),
        v.pop("long", None),
        v.pop("lng", None),
    )

    # extractor_key should only be in playlist table
    cv["extractor_id"] = v.pop("id", None)
    cv["title"] = safe_unpack(v.pop("title", None), v.get("playlist_title"))
    cv["width"] = v.pop("width", None)
    cv["height"] = v.pop("height", None)
    fps = v.pop("fps", None)
    cv["fps"] = 0 if not fps else int(fps)
    cv["live_status"] = v.pop("live_status", None)
    cv["age_limit"] = safe_unpack(
        v.pop("age_limit", None),
        18 if v.pop("is_mature", None) or v.pop("is_nsfw", None) else 0,
    )

    account = v.pop("account", None) or {}
    cv["uploader"] = safe_unpack(
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

    cv["view_count"] = utils.safe_unpack(
        v.pop("view_count", None),
    )
    cv["num_comments"] = utils.safe_unpack(
        v.pop("replies", None),
    )
    cv["favorite_count"] = utils.safe_sum(
        v.pop("favorite_count", None),
        v.pop("likes", None),
        v.pop("note_count", None),
        v.pop("point_count", None),
    )
    cv["score"] = safe_unpack(v.pop("score", None))
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

    return utils.dict_filter_bool(cv)


def add(args, entry):
    if "path" not in entry:
        log.warning('Skipping insert: no "path" in entry %s', entry)
        return

    tags = entry.pop("tags", None) or ""

    media_id = args.db.pop("select id from media where path = ?", [entry["path"]])
    try:
        if media_id:
            entry["id"] = media_id

            args.db["media"].upsert(utils.dict_filter_bool(entry), pk="id", alter=True)
        else:
            args.db["media"].insert(utils.dict_filter_bool(entry), pk="id", alter=True)
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
        fs_tags = utils.dict_filter_bool(fs_extract.extract_metadata(fs_args, local_path), keep_0=False) or {}
        fs_extract.clean_up_temp_dirs()
        with args.db.conn:
            args.db.conn.execute("DELETE from media WHERE path = ?", [webpath])
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
