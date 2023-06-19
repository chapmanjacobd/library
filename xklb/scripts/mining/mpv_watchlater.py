import argparse
from pathlib import Path

from xklb import consts, db, history, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library mpv-watchlater", usage=usage.mpv_watchlater)
    parser.add_argument("--watch-later-directory", default=consts.DEFAULT_MPV_WATCH_LATER, help=argparse.SUPPRESS)

    parser.add_argument("database")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def scan_and_import(args, media) -> None:
    md5s = {utils.path_to_mpv_watchlater_md5(m["path"]): m for m in media}
    paths = set(Path(args.watch_later_directory).glob("*"))

    previously_watched = [
        {
            **(md5s.get(p.stem) or {}),
            "time_first_played": int(p.stat().st_ctime),
            "time_last_played": int(p.stat().st_mtime),
            "playhead": utils.safe_int(utils.mpv_watchlater_value(p, "start")),
        }
        for p in paths
        if md5s.get(p.stem)
    ]

    # create two records if first played and last played time are different
    for m in previously_watched:
        history.add(args, media_ids=[m["id"]], time_played=m["time_first_played"], playhead=m["playhead"])
        if m["time_first_played"] != m["time_last_played"]:
            history.add(args, media_ids=[m["id"]], time_played=m["time_last_played"], playhead=m["playhead"])


def mpv_watchlater():
    args = parse_args()
    media = list(
        args.db.query(
            """
        select id, path from media
        where coalesce(time_deleted, 0) = 0
        """,
        ),
    )
    scan_and_import(args, media)


if __name__ == "__main__":
    mpv_watchlater()
