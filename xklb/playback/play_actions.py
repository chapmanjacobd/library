import argparse, os
from pathlib import Path

from xklb import media_printer, usage
from xklb.createdb import tube_backend
from xklb.folders import big_dirs
from xklb.mediadb import db_history, db_media
from xklb.playback import media_player
from xklb.tablefiles import mcda
from xklb.utils import arggroups, argparse_utils, consts, devices, file_utils, processes, sqlgroups
from xklb.utils.consts import SC
from xklb.utils.log_utils import Timer, log


def parse_args(action, default_chromecast=None) -> argparse.Namespace:
    DEFAULT_PLAYER_ARGS_SUB = ["--speed=1"]
    DEFAULT_PLAYER_ARGS_NO_SUB = ["--speed=1.46"]

    parser = argparse_utils.ArgumentParser(prog="library " + action, usage=usage.play(action))
    arggroups.sql_fs(parser)
    arggroups.playback(parser)
    arggroups.post_actions(parser)
    arggroups.multiple_playback(parser)
    arggroups.clobber(parser)

    arggroups.group_folders(parser)
    arggroups.cluster(parser)
    arggroups.related(parser)

    ordering = parser.add_argument_group("Ordering")
    ordering.add_argument("--play-in-order", "-O", nargs="?", const="natural_ps")
    ordering.add_argument("--fetch-siblings")
    ordering.add_argument(
        "--partial",
        "-P",
        "--previous",
        "--recent",
        default=False,
        const="n",
        nargs="?",
    )

    probabling = parser.add_argument_group("Probability")
    probabling.add_argument(
        "--subtitle-mix", default=consts.DEFAULT_SUBTITLE_MIX, help="Probability to play no-subtitle content"
    )
    probabling.add_argument("--interdimensional-cable", "-4dtv", type=int)

    chromecast = parser.add_argument_group("Chromecast")
    chromecast.add_argument(
        "--chromecast-device",
        "--cast-to",
        "-t",
        default=default_chromecast or "",
    )
    chromecast.add_argument("--chromecast", "--cast", "-c", action="store_true")
    chromecast.add_argument("--cast-with-local", "-wl", action="store_true")

    player = parser.add_argument_group("Player")
    player.add_argument("--player-args-sub", "-player-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_SUB)
    player.add_argument("--player-args-no-sub", "-player-no-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_NO_SUB)
    player.add_argument("--transcode", action="store_true")
    player.add_argument("--transcode-audio", action="store_true")
    player.add_argument("--watch-later-directory", default=consts.DEFAULT_MPV_WATCH_LATER)

    for i in range(0, 255):
        parser.add_argument(f"--cmd{i}", help=argparse.SUPPRESS)

    parser.add_argument("--safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--refresh", action="store_true", help="Check for deleted files before starting playqueue")
    parser.add_argument("--delete-unplayable", action="store_true")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = action

    arggroups.sql_fs_post(args)
    arggroups.playback_post(args)
    arggroups.post_actions_post(args)
    arggroups.multiple_playback_post(args)
    arggroups.group_folders_post(args)

    if args.mpv_socket is None:
        if args.action in (SC.listen,):
            args.mpv_socket = consts.DEFAULT_MPV_LISTEN_SOCKET
        else:
            args.mpv_socket = consts.DEFAULT_MPV_WATCH_SOCKET

    if args.big_dirs:
        args.local_media_only = True

    if args.chromecast:
        from catt.api import CattDevice

        args.cc = CattDevice(args.chromecast_device, lazy=True)
        args.cc_ip = devices.get_ip_of_chromecast(args.chromecast_device)

    arggroups.args_post(args, parser)
    args.sock = None
    return args


def filter_episodic(args, media: list[dict]) -> list[dict]:
    parent_dict = {}
    for m in media:
        path = Path(m["path"])
        parent_path = path.parent
        parent_dict.setdefault(parent_path, 0)
        parent_dict[parent_path] += 1

    filtered_media = []
    for m in media:
        path = Path(m["path"])
        parent_path = path.parent

        siblings = parent_dict[parent_path]

        if not args.folder_counts(siblings):
            continue
        else:
            filtered_media.append(m)

    return filtered_media


def history_sort(args, media) -> list[dict]:
    if "s" in args.partial:  # skip; only play unseen
        previously_watched_paths = [m["path"] for m in media if m["time_first_played"]]
        return [m for m in media if m["path"] not in previously_watched_paths]

    def mpv_progress(m):
        playhead = m.get("playhead")
        duration = m.get("duration")
        if not playhead:
            return float("-inf")
        if not duration:
            return float("-inf")

        if "p" in args.partial and "t" in args.partial:
            return (duration / playhead) * -(duration - playhead)  # weighted remaining
        elif "t" in args.partial:
            return -(duration - playhead)  # time remaining
        else:
            return playhead / duration  # percent remaining

    def sorting_hat():
        if "f" in args.partial:  # first-viewed
            return lambda m: m.get("time_first_played") or 0
        elif "p" in args.partial or "t" in args.partial:  # sort by remaining duration
            return mpv_progress

        return lambda m: m.get("time_last_played") or m.get("time_first_played") or 0

    reverse_chronology = True
    if "o" in args.partial:  # oldest first
        reverse_chronology = False

    key = sorting_hat()
    if args.print:
        reverse_chronology = not reverse_chronology

    media = sorted(
        media,
        key=key,
        reverse=reverse_chronology,
    )

    if args.offset:
        media = media[int(args.offset) :]

    return media


def file_or_folder_media(args, paths):
    media = []
    for path in paths:
        p = Path(path).resolve()
        if p.is_file():
            media.extend([{"path": str(p)}])
        elif p.is_dir():
            if args.folder_glob:
                media.extend([{"path": s} for s in file_utils.fast_glob(p)])
            elif args.action in SC.watch:
                media.extend([{"path": s} for s in file_utils.rglob(str(p), consts.VIDEO_EXTENSIONS)[0]])
            elif args.action == SC.listen:
                media.extend([{"path": s} for s in file_utils.rglob(str(p), consts.AUDIO_ONLY_EXTENSIONS)[0]])
            elif args.action in SC.view:
                media.extend([{"path": s} for s in file_utils.rglob(str(p), consts.IMAGE_EXTENSIONS)[0]])
            elif args.action in SC.read:
                media.extend([{"path": s} for s in file_utils.rglob(str(p), consts.TEXTRACT_EXTENSIONS)[0]])
            else:
                media.extend([{"path": s} for s in file_utils.rglob(str(p))[0]])
    return media


def process_playqueue(args) -> None:
    if args.action == SC.filesystem:
        query, bindings = sqlgroups.fs_sql(args)
    else:
        db_history.create(args)
        query, bindings = sqlgroups.media_sql(args)

    if args.print and not any(
        [
            args.partial,
            args.folder_sizes,
            args.folder_counts,
            args.safe,
            args.play_in_order,
            args.playlists,
            args.big_dirs,
            args.fetch_siblings,
            args.related,
            args.cluster_sort,
            args.folders,
            args.folder_glob,
        ],
    ):
        media_printer.printer(args, query, bindings)
        return

    t = Timer()
    if args.playlists:
        media = db_media.get_playlist_media(args, args.playlists)
    else:
        media = list(args.db.query(query, bindings))
    log.debug("query: %s", t.elapsed())

    if args.fetch_siblings:
        media = db_media.get_sibling_media(args, media)

    if args.partial:
        media = history_sort(args, media)
        log.debug("utils.history_sort: %s", t.elapsed())

    if args.folder_counts:
        media = filter_episodic(args, media)
        log.debug("utils.filter_episodic: %s", t.elapsed())

    if not media:
        if not args.include:
            processes.no_media_found()

        path = " ".join(args.include)
        media = db_media.get_playlist_media(args, [path])
        if not media:
            media = db_media.get_dir_media(args, [path])
        if not media:
            media = file_or_folder_media(args, [path])
        if not media:
            processes.no_media_found()

    if args.safe:
        media = [d for d in media if tube_backend.is_supported(d["path"]) or Path(d["path"]).exists()]
        log.debug("tube_backend.is_supported: %s", t.elapsed())

    if args.related >= consts.RELATED:
        media = db_media.get_related_media(args, media[0])
        log.debug("player.get_related_media: %s", t.elapsed())

    if args.big_dirs:
        media_keyed = {d["path"]: d for d in media}
        folders = big_dirs.group_files_by_parents(args, media)
        dirs = big_dirs.process_big_dirs(args, folders)
        dirs = mcda.group_sort_by(args, dirs)
        log.debug("process_bigdirs: %s", t.elapsed())
        dirs = list(reversed([d["path"] for d in dirs]))
        if "limit" in args.defaults:
            media = db_media.get_dir_media(args, dirs)
            log.debug("get_dir_media: %s", t.elapsed())
        else:
            media = []
            media_set = set()
            for dir in dirs:
                if len(dir) == 1:
                    continue

                for key in media_keyed:
                    if key in media_set:
                        continue

                    if os.sep not in key.replace(dir, "") and key.startswith(dir):
                        media_set.add(key)
                        media.append(media_keyed[key])
            log.debug("double for loop compare_block_strings: %s", t.elapsed())

    if args.play_in_order:
        media = db_media.natsort_media(args, media)

    if args.cluster_sort:
        from xklb.text.cluster_sort import cluster_dicts

        media = cluster_dicts(args, media)
        log.debug("cluster-sort: %s", t.elapsed())

    if getattr(args, "refresh", False):
        marked = db_media.mark_media_deleted(args, [d["path"] for d in media if not Path(d["path"]).exists()])
        log.warning(f"Marked {marked} metadata records as deleted")
        args.refresh = False
        return process_playqueue(args)

    if args.folders:
        unique_folders = set()
        media_unique_folders = []
        for m in media:
            folder_path = str(Path(m["path"]).parent)
            if folder_path not in unique_folders:
                unique_folders.add(folder_path)
                media_unique_folders.append({**m, "path": folder_path})
        media = media_unique_folders
    elif args.folder_glob:
        media = ({"path": s} for m in media for s in file_utils.fast_glob(Path(m["path"]).parent, args.folder_glob))

    if any(
        [
            args.print,
            args.delete_files,
            args.delete_rows,
            args.mark_deleted,
            args.mark_watched,
        ]
    ):
        media_printer.media_printer(args, media)
    else:
        media_player.play_list(args, media)


def watch() -> None:
    args = parse_args(SC.watch, default_chromecast="Living Room TV")
    process_playqueue(args)


def listen() -> None:
    args = parse_args(SC.listen, default_chromecast="Xylo and Orchestra")
    process_playqueue(args)


def filesystem() -> None:
    args = parse_args(SC.filesystem)
    process_playqueue(args)


def read() -> None:
    args = parse_args(SC.read)
    process_playqueue(args)


def view() -> None:
    args = parse_args(SC.view)
    process_playqueue(args)
