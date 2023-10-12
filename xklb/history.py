from xklb.utils import consts, iterables


def create(args):
    args.db.create_table(
        "history",
        {"media_id": int, "time_played": int, "playhead": int, "done": int},
        pk="id",
        if_not_exists=True,
    )


def add(args, paths=None, media_ids=None, time_played=None, playhead=None, mark_done=None):
    media_ids = media_ids or []
    if paths:
        media_ids.extend([args.db.pop("select id from media where path = ?", [path]) for path in paths])

    rows = [
        {
            "media_id": media_id,
            "time_played": time_played or consts.now(),
            "playhead": playhead,
            "done": mark_done,
        }
        for media_id in media_ids
        if media_id
    ]
    args.db["history"].insert_all(iterables.list_dict_filter_bool(rows), pk="id", alter=True)
