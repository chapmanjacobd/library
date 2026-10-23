import argparse, os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from library import usage
from library.database.add import fs_add, fs_add_metadata, tube_backend
from library.folder import big_dirs
from library.database.manage import db_history, db_media
from library.play import media_player, media_printer
from library.table import mcda
from library.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    devices,
    filter_engine,
    iterables,
    nums,
    processes,
    shell_utils,
    sqlgroups,
)
from library.utils.consts import SC, DBType
from library.utils.log_utils import Timer, log


def _configure_parser(action, default_chromecast=None):
    DEFAULT_PLAYER_ARGS_SUB = ["--speed=1"]
    DEFAULT_PLAYER_ARGS_NO_SUB = ["--speed=1.46"]

    parser = argparse_utils.ArgumentParser(usage=usage.play(action))
    arggroups.sql_fs(parser)
    arggroups.files(parser)
    arggroups.playback(parser)
    arggroups.post_actions(parser)
    arggroups.multiple_playback(parser)
    arggroups.clobber(parser)

    arggroups.group_folders(parser)
    arggroups.text_filtering(parser)
    arggroups.cluster_sort(parser)
    arggroups.regex_sort(parser)
    arggroups.related(parser)

    ordering = parser.add_argument_group("Ordering")
    ordering.add_argument(
        "--play-in-order",
        "-O",
        default="natural_ps",
        help="""Play media in order (for similarly named episodes)

-O [option]_[algorithm]_[field]
-O [algorithm]_[field]
-O [algorithm]
(-O [field] if fieldname does not match an algorithm name)

Options:

    - reverse: reverse the sort order
    - compat: treat characters like '⑦' as '7'

Algorithms:

    - natural: parse numbers as integers
    - os: sort similar to the OS File Explorer sorts. To improve non-alphanumeric sorting on Mac OS X and Linux it is necessary to install pyicu (perhaps via python3-icu -- https://gitlab.pyicu.org/main/pyicu#installing-pyicu)
    - path: use natsort "path" algorithm (https://natsort.readthedocs.io/en/stable/api.html#the-ns-enum)
    - human: use system locale
    - ignorecase: treat all case as equal
    - lowercase: sort lowercase first
    - signed: sort with an understanding of negative numbers
    - python: sort like default python
    - none: sqlite ordering / unsorted

Fields:

    - path
    - parent
    - stem
    - title (or any other column field)
    - ps: parent, stem
    - pts: parent, title, stem

Examples:

-O             # natural algorithm and (parent, stem) fields
-O natural_ps  # natural algorithm and (parent, stem) fields

-O title       # natural algorithm (default algorithm) and title field
-O path        # path algorithm and (parent, stem) fields (default field)

-O path_ps     # path algorithm and (parent, stem) fields
-O path_path   # path algorithm and path field

If you prefer SQLite's ordering you can do this instead of -O
-s d/planet.earth.2024/ -u path
""",
    )
    ordering.add_argument("--no-play-in-order", action="store_true")
    ordering.add_argument(
        "--fetch-siblings",
        "--siblings",
        "-o",
        help="""If using --random you need to fetch sibling media to play the media in order:

--fetch-siblings each             # get the first result per directory (SQLite ordering)
--fetch-siblings each -O          # get the first result per directory (natsort ordering)
--fetch-siblings if-audiobook     # get the first result per directory if 'audiobook' is in the path
-u priority -o if-first           # get the first result per directory if the first result was already selected
--fetch-siblings all              # get up to 2,000 results per directory
""",
    )
    ordering.add_argument(
        "--fetch-siblings-max",
        "--siblings-max",
        type=int,
        default=8,
        help="Limit fetch-siblings (no effect to --fetch-siblings all)",
    )
    ordering.add_argument(
        "--re-rank",
        "--rerank",
        "-rr",
        action=argparse_utils.ArgparseDict,
        default={},
        metavar="COLUMN=WEIGHT",
        help="""Add key/value pairs re-rank sorting by multiple attributes (similar to MCDA)
-rr 'regex_sort=1 cluster_sort=1 -size=3'
will sort the playlist by taking into account size, regex, and clusters prioritizing size over the other two.

-u size desc -L 500 --cols path,title,size,time_modified -rs -rr 'regex_sort=2 time_modified=2 sort=1'
will get the 500 largest and then sort by regex_sort, time_modified, and the original sort (size desc)
""",
    )

    probabling = parser.add_argument_group("Probability")
    probabling.add_argument(
        "--subtitle-mix",
        type=float,
        default=consts.DEFAULT_SUBTITLE_MIX,
        help="Probability to prefer content with subtitles",
    )
    probabling.add_argument(
        "--interdimensional-cable",
        "-4dtv",
        type=int,
        help="""Duration to play (in seconds) while changing the channel
--interdimensional-cable 40
-4dtv 40
You can open two terminals to replicate AMV Hell somewhat
library play video --volume 0 -4dtv 30
library play audio -4dtv 30
""",
    )

    chromecast = parser.add_argument_group("Chromecast")
    chromecast.add_argument("--chromecast", "--cast", "-c", action="store_true", help="Cast to chromecast groups")
    chromecast.add_argument(
        "--chromecast-device",
        "--cast-to",
        "-t",
        default=default_chromecast or "",
        help="""--cast --cast-to "Office pair"
-ct "Office pair"  # equivalent

If you don't know the exact name of your chromecast group run `catt scan`
""",
    )
    chromecast.add_argument(
        "--cast-with-local", "-wl", action="store_true", help="Play music locally at the same time as chromecast"
    )

    player = parser.add_argument_group("Player")
    player.add_argument(
        "--player-args-sub",
        "--player-sub",
        nargs="*",
        default=DEFAULT_PLAYER_ARGS_SUB,
        help="Player arguments for videos with subtitles",
    )
    player.add_argument(
        "--player-args-no-sub",
        "--player-no-sub",
        nargs="*",
        default=DEFAULT_PLAYER_ARGS_NO_SUB,
        help="Player arguments for videos without subtitles",
    )
    player.add_argument(
        "--watch-later-directory", default=consts.DEFAULT_MPV_WATCH_LATER, help="Location of mpv watch-later directory"
    )
    player.add_argument(
        "--transcode",
        action="store_true",
        help="Attempt to transcode to a format that will work with chromecast or other players better",
    )
    player.add_argument(
        "--transcode-audio",
        action="store_true",
        help="Attempt to transcode to a format that will work with chromecast or other players better leaving any video streams AS-IS",
    )

    for i in range(255):
        parser.add_argument(f"--cmd{i}", help=argparse.SUPPRESS)

    parser.add_argument("--safe", action="store_true", help="Skip generic URLs")
    parser.add_argument(
        "--exists", "--refresh", action="store_true", help="Check for deleted files before starting playqueue"
    )
    parser.add_argument(
        "--delete-unplayable", action="store_true", help="Delete from disk any media which does not open successfully"
    )
    arggroups.media_scan(parser)
    arggroups.debug(parser)

    arggroups.database_optional(parser)
    arggroups.paths_or_stdin(parser, required=False)

    parser.add_argument("search", nargs="*")
    return parser


def _postprocess_args(args, parser, action):
    for i in range(255):
        if getattr(args, f"cmd{i}") is None:
            delattr(args, f"cmd{i}")

    if args.chromecast and action not in (SC.watch, SC.listen):
        parser.error("--chromecast is supported only with watch or listen")

    arggroups.database_paths_post(args, legacy_database=True)
    arggroups.args_post(args, parser)
    arggroups.sql_fs_post(args)
    arggroups.files_post(args)
    arggroups.playback_post(args)
    arggroups.post_actions_post(args)
    arggroups.multiple_playback_post(args)
    arggroups.group_folders_post(args)
    arggroups.regex_sort_post(args)

    if args.no_play_in_order or args.play_in_order.lower() in ("none", "no", "sqlite", "unsorted", ""):
        args.play_in_order = None

    if args.mpv_socket is None:
        if args.action == SC.listen:
            args.mpv_socket = consts.DEFAULT_MPV_LISTEN_SOCKET
        else:
            args.mpv_socket = consts.DEFAULT_MPV_WATCH_SOCKET

    if args.big_dirs:
        args.local_media_only = True

    if args.chromecast:
        from catt.api import CattDevice

        args.chromecast_device = args.chromecast_device or devices.catt_default_device()
        args.cc = CattDevice(args.chromecast_device, lazy=True)
        args.cc_ip = devices.get_ip_of_chromecast(args.chromecast_device)

    args.sock = None
    return args


def parse_args(action, default_chromecast=None) -> argparse.Namespace:
    parser = _configure_parser(action, default_chromecast)
    args = parser.parse_intermixed_args()
    return _postprocess_args(args, parser, action)


def file_or_folder_media(args, paths):
    media = []
    for path in paths:
        p = Path(path).resolve()
        if p.is_file():
            media.extend([{"path": str(p)}])
        elif p.is_dir():
            if args.folder_glob:
                media.extend([{"path": s} for s in shell_utils.fast_glob(p)])
            elif args.action in SC.watch:
                media.extend([{"path": s} for s in shell_utils.rglob(str(p), consts.VIDEO_EXTENSIONS, args.exclude)[0]])
            elif args.action == SC.listen:
                media.extend(
                    [{"path": s} for s in shell_utils.rglob(str(p), consts.AUDIO_ONLY_EXTENSIONS, args.exclude)[0]]
                )
            elif args.action in SC.view:
                media.extend([{"path": s} for s in shell_utils.rglob(str(p), consts.IMAGE_EXTENSIONS, args.exclude)[0]])
            elif args.action in SC.read:
                media.extend(
                    [{"path": s} for s in shell_utils.rglob(str(p), consts.TEXTRACT_EXTENSIONS, args.exclude)[0]]
                )
            else:
                media.extend([{"path": s} for s in shell_utils.rglob(str(p), exclude=args.exclude)[0]])

    if any(s not in args.defaults for s in ["sizes", "time_modified", "time_created", "type", "no_type"]):
        prefilter_args = arg_utils.args_override(args, {"sort": [], "limit": None})
        media = filter_engine.filter_items_by_criteria(prefilter_args, media)

    if any(s not in args.defaults for s in ["duration", "start", "end"]):
        with ThreadPoolExecutor() as parallel:
            mp_args = argparse.Namespace(
                playlist_path=path, **{k: v for k, v in args.__dict__.items() if k != "db"}
            )
            media = parallel.map(partial(fs_add_metadata.extract_metadata, mp_args), [m["path"] for m in media])
            media = list(filter(None, media))

    return filter_engine.filter_items_by_criteria(args, media)


def folder_media(args, media):
    media = big_dirs.group_files_by_parent(args, media)
    media = big_dirs.process_big_dirs(args, media)
    media = iterables.list_dict_filter_bool(media, keep_0=False)
    return media


def filter_total_size(media, max_size):
    total_size = 0
    for m in media:
        if total_size + m["size"] <= max_size:
            total_size += m["size"]
            yield m
        else:
            break


def _get_database_media(args, filter_engine_obj):
    db_history.create(args)
    m_columns = filter_engine.db_utils.columns(args, "media")
    args.table, m_columns = filter_engine_obj.apply_sql_filters(m_columns)
    args.select_sql = sqlgroups.media_select_sql(args, m_columns)

    if args.action == SC.filesystem:
        def db_sql_func(a):
            return sqlgroups.fs_sql(a, a.limit)
    else:
        db_sql_func = sqlgroups.media_sql

    if args.playlists:
        args.playlists = [p if p.startswith("http") else str(Path(p).resolve()) for p in args.playlists]
        return db_media.get_playlist_media(args, args.playlists)
    media = filter_engine_obj.get_filtered_data(db_sql_func=db_sql_func)
    log.debug("len(media_sql) = %s", len(media))
    return media


def _collect_playqueue_media(args, filter_engine_obj, timer):
    if args.database:
        media = _get_database_media(args, filter_engine_obj)
        log.debug("query: %s", timer.elapsed())
    else:
        media = file_or_folder_media(args, args.paths)
        log.debug("file_or_folder_media: %s", timer.elapsed())
    return media


def _recover_include_media(args, media):
    if media:
        return media
    if not args.include:
        processes.no_media_found()

    include_flat = [i for inc in args.include for i in (inc if isinstance(inc, list) else [inc])]
    path = " ".join(include_flat)
    media = db_media.get_playlist_media(args, [path if path.startswith("http") else str(Path(path).resolve())])
    if not media and os.path.exists(path):
        media = db_media.get_dir_media(args, [path])
    if not media and os.path.exists(include_flat[0]):
        if getattr(args, "fs_add_attempted", False):
            processes.no_media_found()
        args.fs_add_attempted = True
        args.scan_all_files = False
        args.force = False
        args.process = False
        args.check_corrupt = False
        for include_path in include_flat:
            file_count = fs_add.scan_path(args, include_path)
            log.info("Imported %s media", file_count)
            process_playqueue(args)
        return None
    if not media:
        processes.no_media_found()
    return media


def _apply_big_dirs(args, media, timer):
    if not args.big_dirs:
        return media

    media_keyed = {d["path"]: d for d in media}
    folders = big_dirs.group_files_by_parents(args, media)
    folders = big_dirs.process_big_dirs(args, folders)
    folders = mcda.group_sort_by(args, folders)
    log.debug("process_bigdirs: %s", timer.elapsed())
    folders = list(reversed([d["path"] for d in folders]))
    if "limit" in args.defaults:
        media = db_media.get_dir_media(args, folders)
        log.debug("get_dir_media: %s", timer.elapsed())
        return media

    media = []
    media_set = set()
    for folder in folders:
        if len(folder) == 1:
            continue
        for key, media_item in media_keyed.items():
            if key in media_set:
                continue
            if os.sep not in key.replace(folder, "") and key.startswith(folder):
                media_set.add(key)
                media.append(media_item)
    log.debug("double for loop compare_block_strings: %s", timer.elapsed())
    return media


def _apply_playqueue_filters(args, media, _timer):
    if getattr(args, "exists", False):
        marked = db_media.mark_media_deleted(
            args, [d["path"] for d in media if d and d["path"] and not Path(d["path"]).exists()]
        )
        if marked > 0:
            log.warning(f"Marked {marked} metadata records as deleted")
            args.exists = False
            return process_playqueue(args)
    elif args.folders:
        media = folder_media(args, media)
    elif args.folder_glob:
        media = ({"path": s} for m in media for s in shell_utils.fast_glob(Path(m["path"]).parent, args.folder_glob))
    return media


def _sort_reranked_media(args, media, timer):
    import numpy as np
    import pandas as pd

    from library.utils import pd_utils

    df = pd.DataFrame(media)
    df = pd_utils.from_dict_add_path_rank(df, media, "sort")
    if args.regex_sort:
        from library.text import regex_sort

        sorted_media = regex_sort.sort_dicts(args, media)
        df = pd_utils.from_dict_add_path_rank(df, sorted_media, "regex_sort")
        log.debug("regex-sort: %s", timer.elapsed())
    elif args.cluster_sort:
        from library.text import cluster_sort

        sorted_media = cluster_sort.sort_dicts(args, media)
        df = pd_utils.from_dict_add_path_rank(df, sorted_media, "cluster_sort")
        log.debug("cluster-sort: %s", timer.elapsed())

    column_weights = {
        k.lstrip("-"): {
            "direction": "desc" if k.startswith("-") else "asc",
            "weight": v or 1,
        }
        for k, v in args.re_rank.items()
    }
    df = pd_utils.rank_dataframe(df, column_weights)
    return df.replace({np.nan: None}).to_dict(orient="records")


def _sort_playqueue(args, media, timer):
    if args.play_in_order:
        media = db_media.natsort_media(args, media)
    if args.re_rank:
        media = _sort_reranked_media(args, media, timer)
    elif args.regex_sort:
        from library.text import regex_sort

        media = regex_sort.sort_dicts(args, media)
        log.debug("regex-sort: %s", timer.elapsed())
    elif args.cluster_sort:
        from library.text import cluster_sort

        media = cluster_sort.sort_dicts(args, media)
        log.debug("cluster-sort: %s", timer.elapsed())
    return media


def _output_playqueue(args, media):
    if not media:
        processes.no_media_found()
    if any([args.print, args.delete_files, args.delete_rows, args.mark_deleted, args.mark_watched]):
        media_printer.media_printer(args, media)
    elif args.simulate:
        print("Would play:", *(m["path"] for m in media), sep="\n")
    else:
        media_player.play_list(args, media)


def process_playqueue(args) -> None:
    timer = Timer()
    filter_engine_obj = filter_engine.FilterEngine(args)
    media = _collect_playqueue_media(args, filter_engine_obj, timer)

    if args.fetch_siblings:
        media = db_media.get_sibling_media(args, media)

    media = filter_engine_obj.apply_post_filters(media)
    log.debug("apply_post_filters: %s", timer.elapsed())
    media = _recover_include_media(args, media)
    if media is None:
        return

    if args.safe:
        media = [d for d in media if tube_backend.is_supported(d["path"]) or Path(d["path"]).exists()]
        log.debug("tube_backend.is_supported: %s", timer.elapsed())

    if args.related >= consts.RELATED:
        media = db_media.get_related_media(args, media[0])
        log.debug("player.get_related_media: %s", timer.elapsed())

    media = _apply_big_dirs(args, media, timer)
    media = _apply_playqueue_filters(args, media, timer)
    if media is None:
        return
    media = _sort_playqueue(args, media, timer)

    if args.timeout_size:
        max_size = nums.human_to_bytes(args.timeout_size)
        media = filter_total_size(media, max_size)

    _output_playqueue(args, media)
    return


def media() -> None:
    args = parse_args(SC.media)
    args.profiles = [DBType.audio, DBType.image, DBType.video, DBType.text]
    process_playqueue(args)


def watch() -> None:
    args = parse_args(SC.watch, default_chromecast="Living Room TV")
    args.profiles = [DBType.video]
    process_playqueue(args)


def listen() -> None:
    args = parse_args(SC.listen)  # no --cast-to means catt's own default speaker
    args.profiles = [DBType.audio]
    process_playqueue(args)


def read() -> None:
    args = parse_args(SC.read)
    args.profiles = [DBType.text]
    process_playqueue(args)


def view() -> None:
    args = parse_args(SC.view)
    args.profiles = [DBType.image]
    process_playqueue(args)
