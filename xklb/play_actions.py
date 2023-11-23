import argparse, os, shlex, sys
from pathlib import Path
from typing import Dict, List, Tuple

import xklb.db_media
from xklb import history, tube_backend, usage
from xklb.media import media_player, media_printer
from xklb.scripts import big_dirs, mcda
from xklb.utils import consts, db_utils, devices, file_utils, iterables, nums, objects, processes, sql_utils
from xklb.utils.arg_utils import parse_args_limit, parse_args_sort
from xklb.utils.consts import SC
from xklb.utils.log_utils import Timer, log


def parse_args(action, default_chromecast=None) -> argparse.Namespace:
    DEFAULT_PLAYER_ARGS_SUB = ["--speed=1"]
    DEFAULT_PLAYER_ARGS_NO_SUB = ["--speed=1.46"]

    parser = argparse.ArgumentParser(prog="library " + action, usage=usage.play(action))

    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--random", "-r", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--big-dirs", "--bigdirs", "-B", action="count", default=0, help=argparse.SUPPRESS)
    parser.add_argument("--related", "-R", action="count", default=0, help=argparse.SUPPRESS)
    parser.add_argument("--cluster-sort", "--cluster", "-C", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--clusters", "--n-clusters", type=int, help="Number of KMeans clusters")
    parser.add_argument("--play-in-order", "-O", action="count", default=0, help=argparse.SUPPRESS)

    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--flexible-search", "--or", "--flex", action="store_true")
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--no-fts", action="store_true")

    parser.add_argument("--created-within", help=argparse.SUPPRESS)
    parser.add_argument("--created-before", help=argparse.SUPPRESS)
    parser.add_argument("--changed-within", "--modified-within", help=argparse.SUPPRESS)
    parser.add_argument("--changed-before", "--modified-before", help=argparse.SUPPRESS)
    parser.add_argument("--played-within", help=argparse.SUPPRESS)
    parser.add_argument("--played-before", help=argparse.SUPPRESS)
    parser.add_argument("--deleted-within", help=argparse.SUPPRESS)
    parser.add_argument("--deleted-before", help=argparse.SUPPRESS)
    parser.add_argument("--downloaded-within", help=argparse.SUPPRESS)
    parser.add_argument("--downloaded-before", help=argparse.SUPPRESS)

    parser.add_argument(
        "--chromecast-device",
        "--cast-to",
        "-t",
        default=default_chromecast or "",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--chromecast", "--cast", "-c", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cast-with-local", "-wl", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--loop", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--interdimensional-cable", "-4dtv", type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        "--multiple-playback",
        "-m",
        default=False,
        nargs="?",
        const=consts.DEFAULT_MULTIPLE_PLAYBACK,
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--screen-name", help=argparse.SUPPRESS)
    parser.add_argument("--crop", "--zoom", "--stretch", "--fit", "--fill", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--hstack", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--vstack", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--portrait", "-portrait", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--size", "-S", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--duration-from-size", action="append", help=argparse.SUPPRESS)

    parser.add_argument("--print", "-p", default="", const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a column when printing")
    parser.add_argument("--moved", nargs=2, help=argparse.SUPPRESS)

    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--skip", "--offset", help=argparse.SUPPRESS)
    parser.add_argument(
        "--partial",
        "-P",
        "--previous",
        "--recent",
        default=False,
        const="n",
        nargs="?",
        help=argparse.SUPPRESS,
    )

    parser.add_argument("--start", "-vs", help=argparse.SUPPRESS)
    parser.add_argument("--end", "-ve", help=argparse.SUPPRESS)
    parser.add_argument("--mpv-socket", help=argparse.SUPPRESS)
    parser.add_argument("--watch-later-directory", default=consts.DEFAULT_MPV_WATCH_LATER, help=argparse.SUPPRESS)
    parser.add_argument("--subtitle-mix", default=consts.DEFAULT_SUBTITLE_MIX, help=argparse.SUPPRESS)

    parser.add_argument("--no-video", "-vn", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-audio", "-an", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-subtitles",
        "--no-subtitle",
        "--no-subs",
        "--nosubs",
        "-sn",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--subtitles", "--subtitle", "--subs", "-sy", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--volume", type=float)
    parser.add_argument("--auto-seek", action="store_true")
    parser.add_argument("--override-player", "--player", "-player", help=argparse.SUPPRESS)
    parser.add_argument("--player-args-sub", "-player-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_SUB)
    parser.add_argument("--player-args-no-sub", "-player-no-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_NO_SUB)
    parser.add_argument("--transcode", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--transcode-audio", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--post-action", "--action", "-k", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--exit-code-confirm", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--keep-dir", "--keepdir", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--move-replace", action="store_true", help=argparse.SUPPRESS)
    for i in range(0, 255):
        parser.add_argument(f"--cmd{i}", help=argparse.SUPPRESS)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--shallow-organize", default="/mnt/d/", help=argparse.SUPPRESS)

    parser.add_argument("--online-media-only", "--online", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local-media-only", "--local", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")

    parser.add_argument("--sibling", "--episode", action="store_true")
    parser.add_argument("--solo", action="store_true")

    parser.add_argument("--sort-by")
    parser.add_argument("--depth", "-D", default=0, type=int, help="Depth of folders")
    parser.add_argument("--lower", type=int, help="Number of files per folder lower limit")
    parser.add_argument("--upper", type=int, help="Number of files per folder upper limit")
    parser.add_argument("--folder-size", "--foldersize", "-Z", action="append", help=argparse.SUPPRESS)

    parser.add_argument("--prefetch", type=int)
    parser.add_argument("--prefix", default="", help=argparse.SUPPRESS)
    parser.add_argument(
        "--folder",
        action="store_true",
        help="Experimental escape hatch to open folder; breaks a lot of features like post-actions",
    )
    parser.add_argument(
        "--folder-glob",
        "--folderglob",
        type=int,
        default=False,
        const=10,
        nargs="?",
        help="Experimental escape hatch to open a folder glob limited to x number of files; breaks a lot of features like post-actions",
    )

    parser.add_argument("--timeout", "-T", help="Quit after x minutes")
    parser.add_argument("--db", "-db", help="Override the positional argument database location")
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = action
    args.defaults = []

    args.include += args.search
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if len(args.include) == 1 and os.sep in args.include[0]:
        args.include = [file_utils.resolve_absolute_path(args.include[0])]

    if args.db:
        args.database = args.db
    args.db = db_utils.connect(args)

    if args.mpv_socket is None:
        if args.action in (SC.listen):
            args.mpv_socket = consts.DEFAULT_MPV_LISTEN_SOCKET
        else:
            args.mpv_socket = consts.DEFAULT_MPV_WATCH_SOCKET

    if args.big_dirs:
        args.local_media_only = True

    if args.prefetch is None:
        args.prefetch = 1
        if not any([args.play_in_order]):
            args.prefetch = 3

    parse_args_limit(args)
    parse_args_sort(args)

    if args.cols:
        args.cols = list(iterables.flatten([s.split(",") for s in args.cols]))

    if args.duration:
        args.duration = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", args.duration)

    if args.size:
        args.size = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", args.size)

    if args.duration_from_size:
        args.duration_from_size = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", args.duration_from_size)

    if args.chromecast:
        from catt.api import CattDevice

        args.cc = CattDevice(args.chromecast_device, lazy=True)
        args.cc_ip = devices.get_ip_of_chromecast(args.chromecast_device)

    if args.override_player:
        args.override_player = shlex.split(args.override_player)

    if args.multiple_playback > 1:
        args.gui = True

    if args.keep_dir:
        args.keep_dir = Path(args.keep_dir).expanduser().resolve()

    if args.solo:
        args.upper = 1
    if args.sibling:
        args.lower = 2

    if args.post_action:
        args.post_action = args.post_action.replace("-", "_")

    log.info(objects.dict_filter_bool(args.__dict__))

    processes.timeout(args.timeout)

    args.sock = None
    return args


def construct_query(args) -> Tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")

    args.filter_sql = []
    args.aggregate_filter_sql = []
    args.filter_bindings = {}

    if args.duration:
        args.filter_sql.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        args.filter_sql.append(" and size IS NOT NULL " + args.size)
    if args.duration_from_size:
        args.filter_sql.append(
            " and size IS NOT NULL and duration in (select distinct duration from media where 1=1 "
            + args.duration_from_size
            + ")",
        )

    if args.no_video:
        args.filter_sql.append(" and video_count=0 ")
    if args.no_audio:
        args.filter_sql.append(" and audio_count=0 ")
    if args.subtitles:
        args.filter_sql.append(" and subtitle_count>0 ")
    if args.no_subtitles:
        args.filter_sql.append(" and subtitle_count=0 ")

    def ii(string):
        if string.isdigit():
            return string + " minutes"
        return string.replace("mins", "minutes").replace("secs", "seconds")

    if args.created_within:
        args.aggregate_filter_sql.append(
            f"and time_created > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.created_within)}')) as int)",
        )
    if args.created_before:
        args.aggregate_filter_sql.append(
            f"and time_created < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.created_before)}')) as int)",
        )
    if args.changed_within:
        args.aggregate_filter_sql.append(
            f"and time_modified > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.changed_within)}')) as int)",
        )
    if args.changed_before:
        args.aggregate_filter_sql.append(
            f"and time_modified < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.changed_before)}')) as int)",
        )
    if args.played_within:
        args.aggregate_filter_sql.append(
            f"and time_last_played > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.played_within)}')) as int)",
        )
    if args.played_before:
        args.aggregate_filter_sql.append(
            f"and time_last_played < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.played_before)}')) as int)",
        )
    if args.deleted_within:
        args.aggregate_filter_sql.append(
            f"and time_deleted > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.deleted_within)}')) as int)",
        )
    if args.deleted_before:
        args.aggregate_filter_sql.append(
            f"and time_deleted < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.deleted_before)}')) as int)",
        )
    if args.downloaded_within:
        args.aggregate_filter_sql.append(
            f"and time_downloaded > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.downloaded_within)}')) as int)",
        )
    if args.downloaded_before:
        args.aggregate_filter_sql.append(
            f"and time_downloaded < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.downloaded_before)}')) as int)",
        )

    args.table = "media"
    if args.db["media"].detect_fts() and not args.no_fts:
        if args.include:
            args.table, search_bindings = db_utils.fts_search_sql(
                "media",
                fts_table=args.db["media"].detect_fts(),
                include=args.include,
                exclude=args.exclude,
                flexible=args.flexible_search,
            )
            args.filter_bindings = {**args.filter_bindings, **search_bindings}
            m_columns = {**m_columns, "rank": int}
        elif args.exclude:
            db_utils.construct_search_bindings(
                args,
                [f"m.{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
            )
    else:
        db_utils.construct_search_bindings(
            args,
            [f"m.{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
        )

    if args.table == "media" and args.random and not any([args.print, args.limit not in args.defaults]):
        limit = 16 * (args.limit or consts.DEFAULT_PLAY_QUEUE)
        where_not_deleted = (
            "where COALESCE(time_deleted,0) = 0"
            if "time_deleted" in m_columns and "deleted" not in " ".join(sys.argv)
            else ""
        )
        args.filter_sql.append(
            f"and m.id in (select id from media {where_not_deleted} order by random() limit {limit})",
        )

    aggregate_filter_columns = ["time_first_played", "time_last_played", "play_count", "playhead"]

    cols = args.cols or ["path", "title", "duration", "size", "subtitle_count", "is_dir", "rank"]
    if "deleted" in " ".join(sys.argv):
        cols.append("time_deleted")
    if "played" in " ".join(sys.argv):
        cols.append("time_last_played")
    args.select = [c for c in cols if c in m_columns or c in ["*"]] + getattr(args, "select", [])
    if args.action == SC.read and "tags" in m_columns:
        args.select += "cast(length(tags) / 4.2 / 220 * 60 as INT) + 10 duration"
    args.select_sql = "\n        , ".join(args.select)
    args.limit_sql = "LIMIT " + str(args.limit) if args.limit else ""
    args.offset_sql = f"OFFSET {args.skip}" if args.skip and args.limit else ""
    query = f"""WITH m as (
            SELECT
                m.id
                , SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , *
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                {xklb.db_media.filter_args_sql(args, m_columns)}
                {" ".join(args.filter_sql)}
                {" ".join([" and " + w for w in args.where if not any(a in w for a in aggregate_filter_columns)])}
            GROUP BY m.id, m.path
        )
        SELECT
            {args.select_sql}
            , play_count
            , time_first_played
            , time_last_played
            , playhead
        FROM m
        WHERE 1=1
            {" ".join(args.aggregate_filter_sql)}
            {" ".join([" and " + w for w in args.where if any(a in w for a in aggregate_filter_columns)])}
        ORDER BY 1=1
            , {args.sort}
        {args.limit_sql} {args.offset_sql}
    """

    args.filter_sql = [s for s in args.filter_sql if "id" not in s]  # only use random id constraint in first query

    return query, args.filter_bindings


def filter_episodic(args, media: List[Dict]) -> List[Dict]:
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

        if args.lower is not None and siblings < args.lower:
            continue
        elif args.upper is not None and siblings > args.upper:
            continue
        else:
            filtered_media.append(m)

    return filtered_media


def history_sort(args, media) -> List[Dict]:
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

    if args.skip:
        media = media[int(args.skip) :]

    return media


def process_playqueue(args) -> None:
    history.create(args)

    t = Timer()
    query, bindings = construct_query(args)
    log.debug("construct_query: %s", t.elapsed())

    if args.print and not any(
        [
            args.partial,
            args.lower,
            args.upper,
            args.safe,
            args.play_in_order >= consts.SIMILAR,
            args.big_dirs,
            args.related >= consts.RELATED,
            args.cluster_sort,
            args.folder,
            args.folder_glob,
        ],
    ):
        media_printer.printer(args, query, bindings)
        return

    media = list(args.db.query(query, bindings))
    log.debug("query: %s", t.elapsed())

    if args.partial:
        media = history_sort(args, media)
        log.debug("utils.history_sort: %s", t.elapsed())

    if args.lower is not None or args.upper is not None:
        media = filter_episodic(args, media)
        log.debug("utils.filter_episodic: %s", t.elapsed())

    if not media:
        processes.no_media_found()

    if args.safe:
        media = [d for d in media if tube_backend.is_supported(d["path"]) or Path(d["path"]).exists()]
        log.debug("tube_backend.is_supported: %s", t.elapsed())

    if args.related >= consts.RELATED:
        media = xklb.db_media.get_related_media(args, media[0])
        log.debug("player.get_related_media: %s", t.elapsed())

    if args.big_dirs:
        media_keyed = {d["path"]: d for d in media}
        folders = big_dirs.group_files_by_folder(args, media)
        dirs = big_dirs.process_big_dirs(args, folders)
        dirs = mcda.group_sort_by(args, dirs)
        log.debug("process_bigdirs: %s", t.elapsed())
        dirs = list(reversed([d["path"] for d in dirs]))
        if "limit" in args.defaults:
            media = xklb.db_media.get_dir_media(args, dirs)
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

    if args.cluster_sort:
        from xklb.scripts.cluster_sort import cluster_dicts

        media = cluster_dicts(args, media)
        log.debug("cluster-sort: %s", t.elapsed())

    if args.folder:
        media = ({**m, "path": str(Path(m["path"]).parent)} for m in media)
    elif args.folder_glob:
        media = ({"path": s} for m in media for s in file_utils.fast_glob(Path(m["path"]).parent, args.folder_glob))

    if args.print:
        if args.play_in_order >= consts.SIMILAR:
            media = [xklb.db_media.get_ordinal_media(args, d) for d in media]
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
