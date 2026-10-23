import argparse, os, statistics
from collections import defaultdict
from pathlib import Path
from random import randint, shuffle
from statistics import mean, median
from time import sleep

from library import usage
from library.folder import merge_mv
from library.torrent import torrents_start
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    file_utils,
    iterables,
    nums,
    path_utils,
    printing,
    processes,
    shell_utils,
    strings,
)
from library.utils.log_utils import log
from library.utils.path_utils import fqdn_from_url, tld_from_url

MIN_TRANSFER_SPEED = 500
MAX_ETA_SECONDS = 8_640_000
MIN_ALLOCATED_BLOCKS = 12


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_info)
    arggroups.qBittorrent(parser)
    arggroups.qBittorrent_torrents(parser)
    arggroups.qBittorrent_paths(parser)

    parser.add_argument(
        "--sort",
        "-u",
        help="Sort by priority, ratio, download, upload, download+upload, size, avg_size, remaining",
    )

    parser.add_argument("--tag", help="Add a tag to matching torrents")
    parser.add_argument("--untag", "--un-tag", "--no-tag", help="Remove a tag to matching torrents")
    parser.add_argument("--stop", "--pause", action="store_true", help="Stop matching torrents")
    parser.add_argument(
        "--delete-incomplete",
        nargs="?",
        type=nums.float_from_percent,
        const="73%",
        help="Delete incomplete files from matching torrents",
    )
    parser.add_argument(
        "--reset-progress",
        "--reset",
        action="store_true",
        help="Delete matching torrent files and recheck progress without removing the torrent",
    )
    parser.add_argument("--move", type=Path, help="Directory to move folders/files")
    arggroups.mmv_folders(parser)
    parser.add_argument(
        "--move-sizes",
        action="append",
        help="""Move files with --move constrained by file sizes (uses the same syntax as fd-find)""",
    )
    parser.add_argument("--move-limit", type=int, help="Limit number of files transferred")
    parser.add_argument(
        "--move-exclude",
        nargs="+",
        action="extend",
        default=[],
        help="""Exclude files via fnmatch
--move-exclude '*/.tmp/*' '*sad*'  # path must not match neither /.tmp/ nor sad """,
    )
    parser.add_argument(
        "--move-include",
        nargs="+",
        action="extend",
        default=[],
        help="""Include files via fnmatch
--move-include '*/.tmp/*' '*sad*'  # path must match either /.tmp/ or sad """,
    )
    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-src-smaller delete-dest")
    parser.add_argument("--start", action=argparse.BooleanOptionalAction, help="Start matching torrents")
    parser.add_argument("--force-start", action=argparse.BooleanOptionalAction, help="Force start matching torrents")
    parser.add_argument("--download-limit", "--dl-limit", type=nums.human_to_bytes, help="Torrent download limit")
    parser.add_argument(
        "--upload-limit", "--up-limit", "--ul-limit", type=nums.human_to_bytes, help="Torrent upload limit"
    )
    parser.add_argument("--check", "--recheck", action="store_true", help="Check matching torrents")
    parser.add_argument("--wait", action=argparse_utils.ArgparseList, help="Wait for a specific status type")
    parser.add_argument("--export", action="store_true", help="Export matching torrent files")
    parser.add_argument("--add-tracker", action=argparse_utils.ArgparseList, help="Add trackers to matching torrents")
    parser.add_argument(
        "--remove-tracker", action=argparse_utils.ArgparseList, help="Remove trackers from matching torrents"
    )

    arggroups.capability_soft_delete(parser)
    arggroups.capability_delete(parser)
    arggroups.debug(parser)

    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.qBittorrent_torrents_post(args)
    arggroups.mmv_folders_post(args)

    return args


def torrent_files(t):
    import qbittorrentapi

    attempts = 10
    attempt = 0
    while attempt < attempts:
        attempt += 1

        try:
            return t.files
        except (qbittorrentapi.APIConnectionError, ConnectionRefusedError, TimeoutError):
            sleep(randint(1, 10))

    return []


def qbt_get_tracker(qbt_client, torrent):
    import qbittorrentapi

    attempts = 10
    attempt = 0
    while attempt < attempts:
        attempt += 1

        try:
            tracker = torrent.tracker
            if not tracker:
                tracker = iterables.safe_unpack(
                    sorted(
                        (tr.url for tr in qbt_client.torrents_trackers(torrent.hash) if tr.url.startswith("http")),
                        reverse=True,
                    )
                )
            return tld_from_url(tracker)
        except (qbittorrentapi.APIConnectionError, ConnectionRefusedError, TimeoutError):
            sleep(randint(1, 10))

    return None


def qbt_get_tracker_count(qbt_client, torrent):
    import qbittorrentapi

    attempts = 10
    attempt = 0
    while attempt < attempts:
        attempt += 1

        try:
            tracker_count = len(
                set(tr.url for tr in qbt_client.torrents_trackers(torrent.hash) if tr.url.startswith("http"))
            )
            return tracker_count
        except (qbittorrentapi.APIConnectionError, ConnectionRefusedError, TimeoutError):
            sleep(randint(1, 10))

    return None


def qbt_enhance_torrents(qbt_client, qbt_torrents):
    for t in qbt_torrents:
        t.is_active = (not t.state_enum.is_complete and t.downloaded_session > 0) or (
            t.state_enum.is_complete and t.uploaded_session > 0
        )
        t.is_inactive = (not t.state_enum.is_complete and t.downloaded_session == 0) or (
            t.state_enum.is_complete and t.uploaded_session == 0
        )
        t.downloading_time = t.time_active - t.seeding_time
        t.tracker_domain = lambda self=t: qbt_get_tracker(qbt_client, self)
        t.tracker_count = lambda self=t: qbt_get_tracker_count(qbt_client, self)


def filter_torrents_by_activity(args, torrents):
    optional_filters = [
        (args.stopped, lambda t: t.state_enum.is_stopped),
        (args.errored, lambda t: t.state == "error"),
        (args.missing, lambda t: t.state == "missingFiles"),
        (args.moving, lambda t: t.state == "moving"),
        (args.checking, lambda t: t.state.startswith("checking")),
        (args.queued, lambda t: t.state.startswith("queued")),
        (
            args.now,
            lambda t: (
                (not t.state_enum.is_complete and t.dlspeed > MIN_TRANSFER_SPEED)
                or (t.state_enum.is_complete and t.upspeed > MIN_TRANSFER_SPEED)
            ),
        ),
        (
            args.fast,
            lambda t: (
                (not t.state_enum.is_complete and t.dlspeed > 5 * 1000 * 1000)
                or (t.state_enum.is_complete and t.upspeed > 2 * 1000 * 1000)
            ),
        ),
    ]
    for expected, predicate in optional_filters:
        if expected is not None:
            torrents = [t for t in torrents if expected is predicate(t)]

    enabled_filters = [
        (args.complete, lambda t: t.state_enum.is_complete),
        (args.completed, lambda t: t.completion_on > 0),
        (args.incomplete, lambda t: not t.state_enum.is_complete),
        (args.active, lambda t: t.is_active),
        (args.inactive, lambda t: t.is_inactive),
    ]
    for enabled, predicate in enabled_filters:
        if enabled:
            torrents = [t for t in torrents if predicate(t)]
    return torrents


def filter_torrents_by_criteria(args, torrents):
    filters = [
        ("dl_speed", lambda t: args.dl_speed(t.dlspeed)),
        ("ul_speed", lambda t: args.ul_speed(t.upspeed)),
        ("sizes", lambda t: args.sizes(t.total_size)),
        ("file_count", lambda t: args.file_count(len(torrent_files(t)))),
        ("avg_sizes", lambda t: args.avg_sizes(median([f.size for f in torrent_files(t)] or [0]))),
        ("ratio", lambda t: args.ratio(t.ratio)),
        ("seeders", lambda t: args.seeders(t.num_complete)),
        ("leechers", lambda t: args.leechers(t.num_incomplete)),
        ("time_added", lambda t: t.added_on > 0 and args.time_added(consts.APPLICATION_START - t.added_on)),
        (
            "time_stalled",
            lambda t: t.last_activity > 0 and args.time_stalled(consts.APPLICATION_START - t.last_activity),
        ),
        (
            "time_completed",
            lambda t: t.completion_on
            and t.completion_on > 0
            and args.time_completed(consts.APPLICATION_START - t.completion_on),
        ),
        (
            "time_remaining",
            lambda t: (
                (not t.state_enum.is_complete and t.eta and t.eta < MAX_ETA_SECONDS and args.time_remaining(t.eta))
                or (
                    t.state_enum.is_complete
                    and t.upspeed
                    and t.upspeed > MIN_TRANSFER_SPEED
                    and args.time_remaining(t.total_size / t.upspeed)
                )
            ),
        ),
        (
            "time_unseeded",
            lambda t: args.time_unseeded(
                (consts.APPLICATION_START - t.seen_complete)
                if t.num_complete == 0 and t.seen_complete > 0
                else (
                    t.added_on
                    if t.state in ["downloading", "forceDL", "stalledDL", "uploading", "forcedUP", "stalledUP"]
                    and t.num_complete == 0
                    else 0
                )
            ),
        ),
        ("time_active", lambda t: args.time_active(t.time_active)),
        ("time_downloading", lambda t: args.time_downloading(t.downloading_time)),
        ("time_seeding", lambda t: args.time_seeding(t.seeding_time)),
        ("priority", lambda t: args.priority(t.priority)),
        ("progress", lambda t: args.progress(t.progress)),
        ("downloaded", lambda t: args.downloaded(t.downloaded)),
        ("uploaded", lambda t: args.uploaded(t.uploaded)),
        ("downloaded_session", lambda t: args.downloaded_session(t.downloaded_session)),
        ("uploaded_session", lambda t: args.uploaded_session(t.uploaded_session)),
        ("remaining", lambda t: args.remaining(t.amount_left)),
    ]
    for name, predicate in filters:
        if name not in args.defaults:
            torrents = [t for t in torrents if predicate(t)]
    return _filter_torrents_by_extra_criteria(args, torrents)


def _filter_torrents_by_extra_criteria(args, torrents):
    if args.private is not None:
        torrents = [t for t in torrents if args.private is t.private]
    if args.different_drives is not None:
        torrents = [t for t in torrents if torrent_paths_on_different_drives(t) is args.different_drives]
    if args.no_tagged:
        tags = set(args.no_tagged)
        torrents = [t for t in torrents if tags.isdisjoint(t.tags.split(", "))]
    if args.tagged:
        tags = set(args.tagged)
        torrents = [t for t in torrents if tags.issubset(t.tags.split(", "))]
    torrents = _filter_torrents_by_name(args, torrents)
    torrents = _filter_torrents_by_tracker(args, torrents)
    torrents = _filter_torrents_by_paths(args, torrents)
    if args.timeout_size:
        torrents = [t for t in torrents if not processes.sizeout(args.timeout_size, t.total_size)]
        processes.reset_sizeout()
    return torrents


def _filter_torrents_by_name(args, torrents):
    if args.torrent_search:
        torrents = [
            t
            for t in torrents
            if strings.glob_match_all(args.torrent_search, [t.name, t.comment, *torrent_paths_for_search(args, t), t.hash])
        ]
    if args.torrent_exclude:
        torrents = [
            t
            for t in torrents
            if not strings.glob_match_any(
                args.torrent_exclude, [t.name, t.comment, *torrent_paths_for_search(args, t), t.hash]
            )
        ]
    if args.torrent_include:
        torrents = [
            t
            for t in torrents
            if strings.glob_match_any(
                args.torrent_include, [t.name, t.comment, *torrent_paths_for_search(args, t), t.hash]
            )
        ]
    if args.file_search:
        torrents = [t for t in torrents if strings.glob_match_all(args.file_search, [f.name for f in torrent_files(t)])]
    if args.file_exclude:
        torrents = [
            t for t in torrents if not strings.glob_match_any(args.file_exclude, [f.name for f in torrent_files(t)])
        ]
    return torrents


def _filter_torrents_by_tracker(args, torrents):
    if args.tracker:
        trackers = set(args.tracker)
        torrents = [t for t in torrents if t.tracker_domain() in trackers]
    if args.no_tracker:
        trackers = set(args.no_tracker)
        torrents = [t for t in torrents if t.tracker_domain() not in trackers]
    if "tracker_count" not in args.defaults:
        torrents = [t for t in torrents if args.tracker_count(t.tracker_count())]
    return torrents


def _filter_torrents_by_paths(args, torrents):
    def file_path(t, file):
        base_path = t.save_path if t.state_enum.is_complete else t.download_path
        return Path(base_path) / file.name

    if args.any_exists is not None:
        torrents = [
            t for t in torrents if args.any_exists is any(file_path(t, f).exists() for f in torrent_files(t))
        ]
    if args.all_exists is True:
        torrents = [t for t in torrents if all(file_path(t, f).exists() for f in torrent_files(t))]
    elif args.all_exists is False:
        torrents = [t for t in torrents if any(not file_path(t, f).exists() for f in torrent_files(t))]
    if args.opened is not None:
        torrents = [
            t
            for t in torrents
            if args.opened is any(file_utils.is_file_open(file_path(t, f)) for f in torrent_files(t))
        ]
    return torrents


def filter_torrents(args, torrents):
    torrents = filter_torrents_by_activity(args, torrents)
    torrents = filter_torrents_by_criteria(args, torrents)

    if args.limit and "a" not in arggroups.get_compact_print_args(args):
        torrents = torrents[: args.limit]

    if not torrents:
        processes.no_media_found()
    if (args.torrent_search or args.file_search) and not args.print:
        print(len(torrents), "matching torrents")
        print()

    return torrents


def get_error_messages(t):
    errors = []
    for tr in t.trackers:
        msg = tr.msg
        if not msg:
            continue
        if msg == "This torrent is private":
            continue
        errors.append((tr, msg))
    return errors


def print_torrents_by_tracker(args, torrents):
    torrents_by_tracker = {}
    for t in torrents:
        torrents_by_tracker.setdefault(t.tracker_domain(), []).append(t)

    trackers = []
    for tracker, tracker_torrents in torrents_by_tracker.items():
        remaining = sum(t.amount_left for t in tracker_torrents)
        trackers.append(
            {
                "tracker": tracker,
                "count": len(tracker_torrents),
                "size": sum(t.total_size for t in tracker_torrents),
                "remaining": remaining,
                "files": (
                    sum(len(torrent_files(t)) for t in tracker_torrents) if args.file_counts else None
                ),  # a bit slow
            }
        )
    if trackers:
        trackers = sorted(trackers, key=lambda d: (d["remaining"], d["size"]))
        trackers = [
            {
                **d,
                "size": strings.file_size(d["size"]),
                "remaining": strings.file_size(d["remaining"]) if d["remaining"] else None,
            }
            for d in trackers
        ]
        printing.table(iterables.list_dict_filter_bool(trackers))
        print()


def agg_torrents_state(args, state, state_torrents):
    remaining = sum(t.amount_left for t in state_torrents)
    etas = [t.eta for t in state_torrents if t.eta < MAX_ETA_SECONDS]
    if not etas:
        etas = [
            t.total_size / t.upspeed
            for t in state_torrents
            if t.state_enum.is_complete and t.upspeed and t.upspeed > MIN_TRANSFER_SPEED
        ]
    dl_speed = sum(t.dlspeed for t in state_torrents)
    up_speed = sum(t.upspeed for t in state_torrents)
    downloaded = sum(t.downloaded for t in state_torrents)
    downloaded_session = sum(t.downloaded_session for t in state_torrents)
    uploaded = sum(t.uploaded for t in state_torrents)
    uploaded_session = sum(t.uploaded_session for t in state_torrents)

    return {
        "state": state,
        "count": len(state_torrents),
        "files": (sum(len(torrent_files(t)) for t in state_torrents) if args.file_counts else None),
        "size": strings.file_size(sum(t.total_size for t in state_torrents)),
        "downloaded": strings.file_size(downloaded) if downloaded else None,
        "uploaded": strings.file_size(uploaded) if uploaded else None,
        "remaining": strings.file_size(remaining) if remaining else None,
        "next_eta": strings.duration_short(min(etas)) if etas else None,
        "median_eta": strings.duration_short(statistics.median(etas)) if etas else None,
        "session_dl": strings.file_size(downloaded_session) if downloaded_session else None,
        "session_up": strings.file_size(uploaded_session) if uploaded_session else None,
        "dl_speed": strings.file_size(dl_speed) + "/s" if dl_speed else None,
        "up_speed": strings.file_size(up_speed) + "/s" if up_speed else None,
    }


def map_value_status(t, status):
    MAP_VALUE = {
        "stopped": t.state_enum.is_stopped,
        "errored": t.state == "error",
        "missing": t.state == "missingFiles",
        "checking": t.state.startswith("checking"),
        "queued": t.state.startswith("queued"),
        "complete": t.state_enum.is_complete,
        "incomplete": not t.state_enum.is_complete,
    }

    return MAP_VALUE.get(status, t.state == status)


def torrent_paths_for_search(args, t):
    path_search = getattr(args, "path_search", None)
    if path_search is None and getattr(args, "different_drives", None) is not None:
        path_search = "both"
    if path_search is None:
        path_search = "status"
    if path_search == "download":
        return [t.download_path]
    if path_search == "save":
        return [t.save_path]
    if path_search == "both":
        return [t.download_path, t.save_path]
    return [t.save_path if t.state_enum.is_complete else t.download_path]


def torrent_paths_on_different_drives(t):
    if not t.download_path or not t.save_path:
        return False
    return path_utils.mountpoint(t.download_path) != path_utils.mountpoint(t.save_path)


def reset_torrent_progress(qbt_client, torrent):
    originally_stopped = bool(torrent.state_enum.is_stopped)
    qbt_client.torrents_stop(torrent_hashes=[torrent.hash])

    paths = set()
    for file in torrent_files(torrent):
        for base_path in (torrent.download_path, torrent.save_path):
            if base_path:
                paths.add(Path(base_path) / file.name)

    for file_path in paths:
        if file_path.exists() and not file_path.is_dir():
            log.info("Deleting file: %s", file_path)
            file_path.unlink(missing_ok=True)

    qbt_client.torrents_recheck(torrent_hashes=[torrent.hash])
    if not originally_stopped:
        qbt_client.torrents_start(torrent_hashes=[torrent.hash])


def set_torrent_paths(qbt_client, t, temp_path, download_path):
    save_path = download_path if download_path is not None else t.save_path
    if save_path:
        print("      ", t.save_path, "==>", save_path)
        qbt_client.torrents_set_location(str(save_path), torrent_hashes=[t.hash])

    if temp_path is not None:
        print("      ", t.download_path, "-->", temp_path)
        qbt_client.torrents_set_download_path(str(temp_path), torrent_hashes=[t.hash])


def _report_tracker_errors(args, torrents):
    if not (args.errored and args.trackers):
        return
    table = defaultdict(lambda: {"count": 0})
    for torrent in torrents:
        if torrent.is_active and not args.verbose >= consts.LOG_INFO:
            continue
        for tracker, message in get_error_messages(torrent):
            table[fqdn_from_url(tracker.url), message]["count"] += 1
    if table:
        print(f"Error Torrents ({sum(data['count'] for data in table.values())})")
        table_data = [
            {"tracker": tracker, "msg": message, "count": data["count"]}
            for (tracker, message), data in table.items()
        ]
        printing.table(sorted(table_data, key=lambda d: (d["msg"], d["count"], d["tracker"])))
        print()


def _sort_torrents(args, torrents):
    reverse_sort = False
    if args.sort and args.sort.startswith("-"):
        args.sort = args.sort[1:]
        reverse_sort = True

    sorters = {
        "priority": lambda t: t.priority,
        "progress": lambda t: t.progress,
        "ratio": lambda t: t.ratio,
        "remaining": lambda t: t.amount_left,
        "seeders": lambda t: t.num_complete,
        "leechers": lambda t: t.num_incomplete,
        "time_active": lambda t: t.time_active,
        "time_added": lambda t: t.added_on,
        "time_stalled": lambda t: t.last_activity,
        "time_completed": lambda t: t.completion_on,
        "time_remaining": lambda t: (not t.state_enum.is_complete and t.eta and t.eta < MAX_ETA_SECONDS, t.eta),
        "time_unseeded": lambda t: (t.num_complete == 0 and t.seen_complete > 0, t.seen_complete),
        "time_downloading": lambda t: t.downloading_time,
        "time_seeding": lambda t: t.seeding_time,
        "downloaded_session": lambda t: t.downloaded_session,
        "download_session": lambda t: t.downloaded_session,
        "uploaded_session": lambda t: t.uploaded_session,
        "upload_session": lambda t: t.uploaded_session,
        "dl_speed": lambda t: t.dlspeed,
        "dlspeed": lambda t: t.dlspeed,
        "ul_speed": lambda t: t.upspeed,
        "ulspeed": lambda t: t.upspeed,
        "upspeed": lambda t: t.upspeed,
        "tracker": lambda t: t.tracker_domain(),
        "tracker_count": lambda t: t.tracker_count(),
        "counts": lambda t: len(torrent_files(t)),
        "count": lambda t: len(torrent_files(t)),
        "size": lambda t: t.total_size,
        "total_size": lambda t: t.total_size,
        "avg_size": lambda t: mean([f.size for f in torrent_files(t)]),
        "network": lambda t: (
            t.downloaded if not t.state_enum.is_complete else t.uploaded,
            t.downloaded_session if not t.state_enum.is_complete else t.uploaded_session,
        ),
        "download+upload": lambda t: (
            t.downloaded if not t.state_enum.is_complete else t.uploaded,
            t.downloaded_session if not t.state_enum.is_complete else t.uploaded_session,
        ),
        "ingress+egress": lambda t: (
            t.downloaded if not t.state_enum.is_complete else t.uploaded,
            t.downloaded_session if not t.state_enum.is_complete else t.uploaded_session,
        ),
        "downloaded": lambda t: (t.downloaded, t.downloaded_session),
        "download": lambda t: (t.downloaded, t.downloaded_session),
        "ingress": lambda t: (t.downloaded, t.downloaded_session),
        "uploaded": lambda t: (t.uploaded, t.uploaded_session),
        "upload": lambda t: (t.uploaded, t.uploaded_session),
        "egress": lambda t: (t.uploaded, t.uploaded_session),
    }
    if args.sort == "random":
        shuffle(torrents)
    elif args.sort in sorters:
        torrents = sorted(torrents, key=sorters[args.sort], reverse=reverse_sort)
    elif args.move:
        torrents = sorted(torrents, key=lambda t: (t.state_enum.is_complete, t.downloaded))
    elif args.inactive:
        torrents = sorted(
            torrents,
            key=lambda t: (
                not t.state_enum.is_complete,
                t.eta if t.eta < MAX_ETA_SECONDS else 0,
                t.time_active * t.last_activity,
            ),
        )
    else:
        torrents = sorted(
            torrents,
            key=lambda t: (
                not t.state_enum.is_complete,
                t.progress == 0,
                t.eta,
                t.completion_on,
                t.added_on,
            ),
        )
    return torrents


def _shorten_torrent_name(args, name, width):
    return name if args.verbose >= consts.LOG_INFO else strings.shorten(name, width)


def _print_compact_torrents(args, torrents):
    interesting_states = [
        "activeUP",
        "inactiveUP",
        "queuedUP",
        "stoppedUP",
        "stoppedDL",
        "queuedDL",
        "forcedMetaDL",
        "metaDL",
        "inactiveDL",
        "activeDL",
        "missingFiles",
        "error",
    ]
    torrents_by_state = {}
    for torrent in torrents:
        state = torrent.state
        if state not in interesting_states:
            if torrent.state_enum.is_complete:
                state = "activeUP" if torrent.uploaded_session > 0 else "inactiveUP"
            else:
                state = "activeDL" if torrent.downloaded_session > 0 else "inactiveDL"
        torrents_by_state.setdefault(state, []).append(torrent)
    categories = [
        agg_torrents_state(args, state, state_torrents)
        for state, state_torrents in torrents_by_state.items()
    ]
    categories = sorted(categories, key=lambda d: iterables.safe_index(interesting_states, d["state"]))
    if len(categories) > 1:
        categories.append(agg_torrents_state(args, "total", torrents))
    printing.table(iterables.list_dict_filter_bool(categories))
    print()
    if args.trackers:
        print_torrents_by_tracker(args, torrents)


def _torrent_print_base_path(torrent):
    if torrent.state_enum.is_complete:
        base_paths = [torrent.save_path, torrent.content_path, torrent.download_path]
    else:
        base_paths = [torrent.download_path, torrent.content_path, torrent.save_path]
    for test_path in base_paths:
        if test_path and (
            (Path(test_path) / torrent.name).exists()
            or (Path(test_path) / torrent_files(torrent)[0].name).exists()
        ):
            return test_path
    base_path = torrent.save_path if torrent.state_enum.is_complete else torrent.download_path
    return base_path or torrent.content_path


def _print_torrent_paths(args, qbt_client, torrents):
    ignore_trackers = ("** [DHT] **", "** [PeX] **", "** [LSD] **")
    compact_args = arggroups.get_compact_print_args(args)
    for torrent in torrents:
        if "tr" in compact_args:
            for tracker in qbt_client.torrents_trackers(torrent.hash):
                try:
                    if tracker.url not in ignore_trackers:
                        print(tracker.url)
                except UnicodeDecodeError:
                    pass
            continue
        base_path = _torrent_print_base_path(torrent)
        if base_path is None:
            log.warning("%s files do not exist", torrent.name)
            continue
        if "f" in compact_args:
            for file in torrent_files(torrent):
                print(Path(base_path) / file.name)
        else:
            print(Path(base_path) / torrent.name)


def _add_common_torrent_row_fields(args, torrent, row, verbose_fields):
    if args.sizes or args.avg_sizes or args.move or (args.sort and "size" in args.sort):
        row["size"] = strings.file_size(torrent.total_size)
    if args.sort == "priority":
        row["priority"] = str(torrent.priority) + (" [F]" if torrent.force_start else "")
    if args.trackers:
        row["tracker"] = torrent.tracker_domain()
    if args.file_search:
        files = torrent_files(torrent)
        files = [f for f in torrent_files(torrent) if strings.glob_match_all(args.file_search, [f.name])]
        print(torrent.name)
        printing.extended_view(files)
        print()
        row["files"] = f"{len(files)} ({len(torrent_files(torrent))})"
    elif args.file_counts:
        row["files"] = len(torrent_files(torrent))
    if args.paths:
        row["path"] = torrent.save_path if torrent.state_enum.is_complete else torrent.download_path
    if args.verbose >= consts.LOG_INFO:
        row |= verbose_fields(torrent)


def _inactive_torrent_row(args, torrent):
    row = {
        "name": _shorten_torrent_name(args, torrent.name, 35),
        "num_seeds": f"{torrent.num_seeds} ({torrent.num_complete})",
        "progress": strings.percent(torrent.progress),
        "seen_complete": strings.relative_datetime(torrent.seen_complete) if torrent.seen_complete > 0 else "",
        "last_activity": strings.relative_datetime(torrent.last_activity),
    }
    if args.status or args.verbose >= consts.LOG_INFO:
        row["state"] = torrent.state
    if not torrent.state_enum.is_complete:
        row |= {
            "duration": strings.duration_short(torrent.downloading_time),
            "downloaded": strings.file_size(torrent.downloaded),
            "remaining": strings.file_size(torrent.amount_left) if torrent.amount_left > 0 else None,
        }
    if torrent.state_enum.is_complete:
        row |= {"duration": strings.duration_short(torrent.seeding_time), "uploaded": strings.file_size(torrent.uploaded)}
    _add_common_torrent_row_fields(
        args,
        torrent,
        row,
        lambda t: {
            "completed_on": strings.relative_datetime(t.completion_on) if t.completion_on > 0 else None,
            "added_on": strings.relative_datetime(t.added_on) if t.added_on > 0 else None,
            "comment": t.comment,
            "download_path": t.download_path,
            "save_path": t.save_path,
            "content_path": t.content_path,
        },
    )
    return row


def _active_torrent_row(args, torrent):
    row = {
        "name": _shorten_torrent_name(args, torrent.name, 35),
        "num_seeds": f"{torrent.num_seeds} ({torrent.num_complete})",
        "progress": strings.percent(torrent.progress),
    }
    if args.status or args.verbose >= consts.LOG_INFO:
        row["state"] = torrent.state
    if not torrent.state_enum.is_complete:
        row |= {
            "duration": strings.duration_short(torrent.downloading_time),
            "session": strings.file_size(torrent.downloaded_session),
            "remaining": strings.file_size(torrent.amount_left) if torrent.amount_left > 0 else None,
            "speed": strings.file_size(torrent.dlspeed) + "/s" if torrent.dlspeed else None,
            "eta": strings.duration_short(torrent.eta) if torrent.eta < MAX_ETA_SECONDS else None,
        }
    if torrent.state_enum.is_complete:
        row |= {
            "duration": strings.duration_short(torrent.seeding_time),
            "session": strings.file_size(torrent.uploaded_session),
            "uploaded": strings.file_size(torrent.uploaded),
            "speed": strings.file_size(torrent.upspeed) + "/s" if torrent.upspeed else None,
            "eta": (
                strings.duration_short(torrent.total_size / torrent.upspeed)
                if torrent.upspeed and torrent.upspeed > MIN_TRANSFER_SPEED
                else None
            ),
        }
    _add_common_torrent_row_fields(
        args,
        torrent,
        row,
        lambda t: {
            "seen_complete": strings.relative_datetime(t.seen_complete) if t.seen_complete > 0 else None,
            "completed_on": strings.relative_datetime(t.completion_on) if t.completion_on > 0 else None,
            "added_on": strings.relative_datetime(t.added_on) if t.added_on > 0 else None,
            "last_activity": strings.relative_datetime(t.last_activity) if t.last_activity > 0 else None,
            "comment": t.comment,
            "download_path": t.download_path,
            "save_path": t.save_path,
            "content_path": t.content_path,
        },
    )
    return row


def _print_detailed_torrents(args, torrents):
    inactive_torrents = [t for t in torrents if t.is_inactive]
    if inactive_torrents:
        print(f"Inactive Torrents ({len(inactive_torrents)})")
        printing.table(iterables.conform([_inactive_torrent_row(args, t) for t in inactive_torrents]))
        print()
    active_torrents = [t for t in torrents if t.is_active]
    if active_torrents:
        print(f"Active Torrents ({len(active_torrents)})")
        printing.table(iterables.conform([_active_torrent_row(args, t) for t in active_torrents]))
        print()


def _print_torrents(args, qbt_client, torrents):
    if args.print and "a" in arggroups.get_compact_print_args(args):
        _print_compact_torrents(args, torrents)
    elif args.print:
        _print_torrent_paths(args, qbt_client, torrents)
    else:
        _print_detailed_torrents(args, torrents)


def _delete_incomplete_torrents(args, torrents):
    if not args.delete_incomplete:
        return
    for torrent in torrents:
        base_paths = (
            [torrent.save_path, torrent.download_path]
            if torrent.state_enum.is_complete
            else [torrent.download_path, torrent.save_path]
        )
        invalid_state = torrent.state.startswith("checking") or torrent.state in ("missingFiles", "error")
        if invalid_state:
            continue
        for file in torrent_files(torrent):
            if invalid_state:
                break
            for base_path in base_paths:
                file_path = Path(base_path) / file.name
                if file_path.exists() and not file_path.is_dir():
                    if file.progress == 0.0:
                        stat = file_path.stat()
                        if stat.st_blocks and stat.st_blocks > MIN_ALLOCATED_BLOCKS:
                            log.error(
                                "Skipping the rest of torrent because invalid state likely. Recheck first. %s",
                                torrent.name,
                            )
                            invalid_state = True
                            break
                    if file.progress < args.delete_incomplete:
                        log.warning("Deleting incomplete file: %s", file_path)
                        shell_utils.trash(args, str(file_path), detach=False)
                    elif file.progress == 1.0:
                        log.info("Keeping complete file: %s", file_path)
                    else:
                        log.warning("Keeping %s incomplete file: %s", strings.percent(1 - file.progress), file_path)
                    break


def _resolve_move_path(args, torrent, path, prefix_name, existing_path):
    if path:
        if not path.is_absolute():
            path = Path(path_utils.mountpoint(torrent.content_path)) / path
        if os.path.isfile(path):
            path = path.parent
        elif os.path.isdir(path) and path_utils.basename(path) == path_utils.basename(existing_path):
            pass
        else:
            prefix = getattr(args, prefix_name)
            if prefix and prefix not in path.parts:
                path /= prefix
            if args.tracker_dirnames:
                domain = torrent.tracker_domain()
                if domain and domain not in path.parts:
                    path /= domain
    return path


def _torrent_move_paths(args, torrent):
    if "temp_drive" not in args.defaults:
        temp_path = Path(args.temp_drive)
    elif "temp_prefix" not in args.defaults:
        temp_path = Path(path_utils.mountpoint(torrent.download_path or torrent.content_path))
        log.debug("temp_path: using t.download_path %s mountpoint %s", torrent.download_path, temp_path)
    else:
        temp_path = args.move
    if "download_drive" not in args.defaults:
        download_path = Path(args.download_drive)
    elif "download_prefix" not in args.defaults:
        download_path = Path(path_utils.mountpoint(torrent.save_path or torrent.content_path))
        log.debug("download_path: using t.save_path %s mountpoint %s", torrent.save_path, download_path)
    else:
        download_path = args.move
    temp_path = _resolve_move_path(args, torrent, temp_path, "temp_prefix", torrent.download_path or torrent.content_path)
    download_path = _resolve_move_path(args, torrent, download_path, "download_prefix", torrent.save_path or torrent.content_path)
    log.debug("temp_path %s", temp_path)
    log.debug("download_path %s", download_path)
    return temp_path, download_path


def _move_torrent(args, qbt_client, torrent):
    originally_stopped = bool(torrent.state_enum.is_stopped)
    qbt_client.torrents_stop(torrent_hashes=[torrent.hash])
    temp_path, download_path = _torrent_move_paths(args, torrent)
    new_path = download_path if torrent.state_enum.is_complete else temp_path
    if new_path is None:
        new_path = torrent.save_path if torrent.state_enum.is_complete else torrent.download_path
    if args.simulate:
        print("Moving", torrent.content_path, "to", new_path)
        return
    content_path = Path(torrent.content_path) if torrent.content_path else None
    if content_path and content_path.exists() and new_path is not None:
        if content_path.is_file():
            print("Moving file", content_path, "to", new_path)
            merge_mv.move(args, [str(content_path)], str(new_path))
        else:
            new_path = Path(new_path) / content_path.name
            print("Moving folder", content_path, "to", new_path)
            merge_mv.move(args, [str(content_path)], str(new_path))
    if not (args.delete_files or args.delete_rows):
        set_torrent_paths(qbt_client, torrent, temp_path, download_path)
        if not originally_stopped:
            qbt_client.torrents_start(torrent_hashes=[torrent.hash])


def _move_torrents(args, qbt_client, torrents):
    alt_move_syntax = any(
        k not in args.defaults for k in ["temp_drive", "temp_prefix", "download_drive", "download_prefix"]
    )
    if args.move or alt_move_syntax:
        for index, torrent in enumerate(torrents):
            print("Moving", index + 1, "of", len(torrents))
            _move_torrent(args, qbt_client, torrent)


def _apply_tags_and_state(args, qbt_client, torrents, torrent_hashes):
    if args.tag:
        print("Tagging", len(torrents))
        qbt_client.torrents_add_tags(args.tag, torrent_hashes=torrent_hashes)
    if args.untag:
        print("Untagging", len(torrents))
        qbt_client.torrents_remove_tags(args.untag, torrent_hashes=torrent_hashes)
    if args.stop:
        print("Stopping", len(torrents))
        qbt_client.torrents_stop(torrent_hashes=torrent_hashes)


def _apply_limits_and_checks(args, qbt_client, torrents, torrent_hashes):
    if args.start:
        print("Starting", len(torrents))
        qbt_client.torrents_start(torrent_hashes=torrent_hashes)
    if args.force_start is not None:
        print("Setting force-start" if args.force_start else "Setting normal-start", len(torrents))
        qbt_client.torrents_set_force_start(args.force_start, torrent_hashes=torrent_hashes)
    if args.download_limit is not None:
        print("Setting DL limit" if args.download_limit else "Removing DL limit", len(torrents))
        qbt_client.torrents_set_download_limit(args.download_limit or -1, torrent_hashes=torrent_hashes)
    if args.upload_limit is not None:
        print("Setting UP limit" if args.upload_limit else "Removing UP limit", len(torrents))
        qbt_client.torrents_set_upload_limit(args.upload_limit or -1, torrent_hashes=torrent_hashes)
    if args.check:
        print("Checking", len(torrents))
        qbt_client.torrents_recheck(torrent_hashes=torrent_hashes)


def _apply_tracker_actions(args, qbt_client, torrents):
    if args.add_tracker:
        for index, torrent in enumerate(torrents):
            printing.print_overwrite("Adding tracker", index + 1, "of", len(torrents), args.add_tracker)
            qbt_client.torrents_add_trackers(torrent.hash, args.add_tracker)
        print()
    if args.remove_tracker:
        for index, torrent in enumerate(torrents):
            printing.print_overwrite("Removing tracker", index + 1, "of", len(torrents), args.remove_tracker)
            qbt_client.torrents_remove_trackers(torrent.hash, args.remove_tracker)
        print()


def _export_torrents(args, qbt_client, torrents):
    if args.export:
        export_path = Path("exported_torrents")
        export_path.mkdir(exist_ok=True)
        for index, torrent in enumerate(torrents):
            printing.print_overwrite("Exporting", index + 1, "of", len(torrents), "to", export_path)
            file_name = path_utils.clean_path(
                f"{torrent.tracker_domain()}_{torrent.name}_{torrent.hash}.torrent".encode()
            )
            (export_path / file_name).write_bytes(qbt_client.torrents_export(torrent_hash=torrent.hash))
        print()


def _delete_torrents(args, qbt_client, torrents, torrent_hashes):
    if args.mark_deleted:
        print("Marking deleted", len(torrents))
        qbt_client.torrents_add_tags(tags="library-delete", torrent_hashes=torrent_hashes)
    elif args.delete_files:
        print("Deleting files of", len(torrents))
        actually_delete_files = not (args.move or args.delete_incomplete)
        qbt_client.torrents_delete(delete_files=actually_delete_files, torrent_hashes=torrent_hashes)
    elif args.delete_rows:
        print("Deleting from qBit", len(torrents))
        qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent_hashes)


def _wait_for_torrents(args, qbt_client, torrents):
    if not args.wait:
        return
    for index, torrent in enumerate(torrents):
        print("Waiting for", index + 1, "of", len(torrents), "to be one of:", ", ".join(args.wait))
        while True:
            refreshed_torrents = qbt_client.torrents_info(torrent_hashes=torrent.hash)
            if not refreshed_torrents:
                log.error("Torrent %s not found %s", torrent.name, torrent.hash)
                break
            if len(refreshed_torrents) > 1:
                log.warning("More than one torrent matched %s: %s", torrent.hash, refreshed_torrents)
            current_torrent = refreshed_torrents[0]
            if any(map_value_status(current_torrent, status) for status in args.wait):
                break
            sleep(3)


def _apply_torrent_actions(args, qbt_client, torrents):
    torrent_hashes = [t.hash for t in torrents]
    _apply_tags_and_state(args, qbt_client, torrents, torrent_hashes)
    _delete_incomplete_torrents(args, torrents)
    if args.reset_progress:
        print("Resetting progress of", len(torrents))
        for torrent in torrents:
            reset_torrent_progress(qbt_client, torrent)
    _move_torrents(args, qbt_client, torrents)
    _apply_limits_and_checks(args, qbt_client, torrents, torrent_hashes)
    _apply_tracker_actions(args, qbt_client, torrents)
    _export_torrents(args, qbt_client, torrents)
    _delete_torrents(args, qbt_client, torrents, torrent_hashes)
    _wait_for_torrents(args, qbt_client, torrents)


def torrents_info():
    args = parse_args()
    if args.simulate:
        print("Simulation: no torrent changes made")
        return

    qbt_client = torrents_start.start_qBittorrent(args)
    torrents = qbt_client.torrents_info()
    qbt_enhance_torrents(qbt_client, torrents)
    _report_tracker_errors(args, torrents)
    if any(t.state_enum.is_errored for t in torrents):
        args.status = True
    torrents = _sort_torrents(args, torrents)
    torrents = filter_torrents(args, torrents)
    _print_torrents(args, qbt_client, torrents)
    _apply_torrent_actions(args, qbt_client, torrents)
