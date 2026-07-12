import os
import re
from collections import defaultdict

_REQUIRED_MEDIA_COLUMNS = {"path", "size", "duration", "time_deleted"}
_MIN_PATH_PARTS = 2
_FOLDER_STATS_COLUMNS = {
    "parent",
    "depth",
    "file_count",
    "total_size",
    "total_duration",
    "direct_file_count",
    "direct_size",
    "direct_duration",
    "folder_count",
}


def _columns(db, table_name):
    return {row[1] for row in db.execute(f"PRAGMA table_info([{table_name}])").fetchall()}


def ensure(db) -> bool:
    if "media" not in db.table_names():
        return False
    if not _REQUIRED_MEDIA_COLUMNS.issubset(_columns(db, "media")):
        return False

    folder_stats_columns = _columns(db, "folder_stats") if "folder_stats" in db.table_names() else set()
    if folder_stats_columns and not _FOLDER_STATS_COLUMNS.issubset(folder_stats_columns):
        db.execute("DROP TABLE IF EXISTS folder_stats")
        db.execute("DROP TABLE IF EXISTS folder_stats_meta")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS folder_stats (
            parent TEXT PRIMARY KEY,
            depth INTEGER NOT NULL,
            file_count INTEGER NOT NULL,
            total_size INTEGER NOT NULL,
            total_duration INTEGER NOT NULL,
            direct_file_count INTEGER NOT NULL,
            direct_size INTEGER NOT NULL,
            direct_duration INTEGER NOT NULL,
            folder_count INTEGER NOT NULL
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_folder_stats_depth ON folder_stats(depth)")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS folder_stats_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            dirty INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    db.execute("INSERT OR IGNORE INTO folder_stats_meta (id, dirty) VALUES (1, 1)")

    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS folder_stats_media_insert
        AFTER INSERT ON media
        BEGIN
            UPDATE folder_stats_meta SET dirty = 1 WHERE id = 1;
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS folder_stats_media_delete
        AFTER DELETE ON media
        BEGIN
            UPDATE folder_stats_meta SET dirty = 1 WHERE id = 1;
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS folder_stats_media_update
        AFTER UPDATE OF path, size, duration, time_deleted ON media
        BEGIN
            UPDATE folder_stats_meta SET dirty = 1 WHERE id = 1;
        END
        """
    )
    return True


def _parents(path):
    parts = str(path).split(os.sep)
    while len(parts) >= _MIN_PATH_PARTS:
        parts.pop()
        yield os.sep.join(parts)


def _depth(parent):
    return len(parent.split(os.sep))


def _refresh(db) -> None:
    stats = defaultdict(
        lambda: {
            "file_count": 0,
            "total_size": 0,
            "total_duration": 0,
            "direct_file_count": 0,
            "direct_size": 0,
            "direct_duration": 0,
            "folder_count": 0,
        }
    )
    direct_parents = set()
    for media in db.query(
        """
        SELECT path, COALESCE(size, 0) AS size, COALESCE(duration, 0) AS duration
        FROM media
        WHERE COALESCE(time_deleted, 0) = 0
        """
    ):
        parents = list(_parents(media["path"]))
        if not parents:
            continue

        size = media["size"] or 0
        duration = media["duration"] or 0
        direct_parents.add(parents[0])
        for index, parent in enumerate(parents):
            data = stats[parent]
            data["file_count"] += 1
            data["total_size"] += size
            data["total_duration"] += duration
            if index == 0:
                data["direct_file_count"] += 1
                data["direct_size"] += size
                data["direct_duration"] += duration

    for parent in direct_parents:
        for ancestor in _parents(parent):
            stats[ancestor]["folder_count"] += 1

    with db.conn:
        db.execute("DELETE FROM folder_stats")
        db.conn.executemany(
            """
            INSERT INTO folder_stats (
                parent,
                depth,
                file_count,
                total_size,
                total_duration,
                direct_file_count,
                direct_size,
                direct_duration,
                folder_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    parent,
                    _depth(parent),
                    data["file_count"],
                    data["total_size"],
                    data["total_duration"],
                    data["direct_file_count"],
                    data["direct_size"],
                    data["direct_duration"],
                    data["folder_count"],
                )
                for parent, data in stats.items()
            ],
        )
        db.execute("UPDATE folder_stats_meta SET dirty = 0 WHERE id = 1")


def refresh(db) -> None:
    if ensure(db):
        _refresh(db)


def refresh_if_needed(db) -> bool:
    if not ensure(db):
        return False
    if db.pop("SELECT dirty FROM folder_stats_meta WHERE id = 1") != 0:
        _refresh(db)
    return True


def can_use(args) -> bool:
    if not getattr(args, "database", None) or not getattr(args, "folders_only", False):
        return False
    if not getattr(args, "hide_deleted", False):
        return False
    if any(
        getattr(args, name, None)
        for name in (
            "group_by_extensions",
            "group_by_mimetypes",
            "group_by_size",
            "include",
            "exclude",
            "where",
            "offset",
            "only_deleted",
            "ext",
            "type",
            "no_type",
            "sizes",
            "bitrates",
            "duration",
            "duration_from_size",
            "time_created",
            "time_modified",
            "time_deleted",
            "created_within",
            "created_before",
            "modified_within",
            "modified_before",
            "deleted_within",
            "deleted_before",
            "downloaded_within",
            "downloaded_before",
            "played_within",
            "played_before",
            "partial",
            "local_media_only",
            "online_media_only",
            "no_video",
            "no_audio",
            "subtitles",
            "no_subtitles",
        )
    ):
        return False

    filters = {re.sub(r"\s+", "", value).lower() for value in getattr(args, "filter_sql", [])}
    return filters in (set(), {"andcoalesce(m.time_deleted,0)=0"})


def get_subset(args):
    if not can_use(args):
        return None

    from library.fsdb import disk_usage

    db = args.db
    if not refresh_if_needed(db):
        return None

    recursive = args.parents
    rows = db.query(
        """
        SELECT parent, file_count, total_size, total_duration,
               direct_file_count, direct_size, direct_duration, folder_count
        FROM folder_stats
        WHERE depth >= ?
          AND (? IS NULL OR depth <= ?)
        """,
        [args.min_depth, args.max_depth, args.max_depth],
    )
    subset = [
        {
            "path": disk_usage.format_folder(row["parent"]),
            "count": row["file_count"] if recursive else row["direct_file_count"],
            "size": row["total_size"] if recursive else row["direct_size"],
            "duration": row["total_duration"] if recursive else row["direct_duration"],
            "folders": row["folder_count"],
        }
        for row in rows
        if (row["file_count"] if recursive else row["direct_file_count"]) > 0
    ]
    return sorted(
        subset,
        key=disk_usage.sort_by(args),
        reverse=not bool(args.sort_groups_by and " desc" in args.sort_groups_by),
    )
