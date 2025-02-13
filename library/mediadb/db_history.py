import sqlite3

from library.utils import consts, iterables
from library.utils.log_utils import log


def create(args):
    args.db.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER NOT NULL,
            time_played INTEGER DEFAULT (strftime('%s', 'now')),
            playhead INTEGER,
            done INTEGER
        ) STRICT;
        """
    )
    args.db.execute("CREATE INDEX IF NOT EXISTS history_media_idx ON history (media_id);")


def exists(args, media_id) -> bool:
    try:
        known = args.db.execute(
            "select 1 from history where media_id=?",
            [media_id],
        ).fetchone()
    except sqlite3.OperationalError as e:
        log.debug(e)
        return False
    if known is None:
        return False
    return True


def add(args, paths=None, media_ids=None, time_played=None, playhead=None, mark_done=None):
    media_ids = media_ids or []
    if paths:
        media_ids.extend([args.db.pop("select id from media where path = ?", [path]) for path in paths])

    rows = [
        {
            "media_id": media_id,
            "time_played": time_played or consts.now(),
            "playhead": playhead or 0,
            "done": mark_done,
        }
        for media_id in media_ids
        if media_id
    ]
    args.db["history"].insert_all(iterables.list_dict_filter_bool(rows), alter=True)
    return len(media_ids)


def remove(args, paths=None, media_ids=None):
    media_ids = media_ids or []
    if paths:
        media_ids.extend([args.db.pop("SELECT id from media WHERE path = ?", [path]) for path in paths])

    with args.db.conn:
        for media_id in media_ids:
            args.db.conn.execute("DELETE from history WHERE media_id = ?", [media_id])
