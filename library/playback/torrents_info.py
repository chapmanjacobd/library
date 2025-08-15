#!/usr/bin/python3
import argparse, os, statistics
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from time import sleep

from library import usage
from library.folders import merge_mv
from library.mediafiles import torrents_start
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
    strings,
)
from library.utils.log_utils import log
from library.utils.path_utils import fqdn_from_url, tld_from_url


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
    parser.add_argument("--stop", action="store_true", help="Stop matching torrents")
    parser.add_argument(
        "--delete-incomplete",
        nargs="?",
        type=nums.float_from_percent,
        const="73%",
        help="Delete incomplete files from matching torrents",
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


def qbt_get_tracker(qbt_client, torrent):
    tracker = torrent.tracker
    if not tracker:
        tracker = iterables.safe_unpack(
            sorted(
                (tr.url for tr in qbt_client.torrents_trackers(torrent.hash) if tr.url.startswith("http")), reverse=True
            )
        )
    return tld_from_url(tracker)


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


def filter_torrents_by_activity(args, torrents):
    if args.stopped is not None:
        torrents = [t for t in torrents if args.stopped is t.state_enum.is_stopped]
    if args.errored is not None:
        torrents = [t for t in torrents if args.errored is (t.state == "error")]
    if args.missing is not None:
        torrents = [t for t in torrents if args.missing is (t.state == "missingFiles")]
    if args.moving is not None:
        torrents = [t for t in torrents if args.moving is (t.state == "moving")]
    if args.checking is not None:
        torrents = [t for t in torrents if args.checking is t.state.startswith("checking")]
    if args.queued is not None:
        torrents = [t for t in torrents if args.queued is t.state.startswith("queued")]

    if args.complete:
        torrents = [t for t in torrents if t.state_enum.is_complete]
    if args.incomplete:
        torrents = [t for t in torrents if not t.state_enum.is_complete]

    if args.active:
        torrents = [t for t in torrents if t.is_active]
    if args.inactive:
        torrents = [t for t in torrents if t.is_inactive]
    if args.now:
        torrents = [
            t
            for t in torrents
            if (not t.state_enum.is_complete and t.dlspeed > 500) or (t.state_enum.is_complete and t.upspeed > 500)
        ]

    return torrents


def filter_torrents_by_criteria(args, torrents):
    if "sizes" not in args.defaults:
        torrents = [t for t in torrents if args.sizes(t.total_size)]
    if "file_count" not in args.defaults:
        torrents = [t for t in torrents if args.file_count(len(t.files))]
    if "avg_sizes" not in args.defaults:
        torrents = [t for t in torrents if args.avg_sizes(median([f.size for f in t.files]))]
    if "ratio" not in args.defaults:
        torrents = [t for t in torrents if args.ratio(t.ratio)]
    if "seeders" not in args.defaults:
        torrents = [t for t in torrents if args.seeders(t.num_complete)]
    if "leechers" not in args.defaults:
        torrents = [t for t in torrents if args.leechers(t.num_incomplete)]
    if "time_added" not in args.defaults:
        torrents = [t for t in torrents if t.added_on > 0 and args.time_added(consts.APPLICATION_START - t.added_on)]
    if "time_stalled" not in args.defaults:
        torrents = [
            t for t in torrents if t.last_activity > 0 and args.time_stalled(consts.APPLICATION_START - t.last_activity)
        ]
    if "time_completed" not in args.defaults:
        torrents = [
            t
            for t in torrents
            if t.completion_on
            and t.completion_on > 0
            and args.time_completed(consts.APPLICATION_START - t.completion_on)
        ]
    if "time_remaining" not in args.defaults:
        torrents = [
            t
            for t in torrents
            if (not t.state_enum.is_complete and t.eta and t.eta < 8640000 and args.time_remaining(t.eta))
            or (
                t.state_enum.is_complete
                and t.upspeed
                and t.upspeed > 500
                and args.time_remaining(t.total_size / t.upspeed)
            )
        ]
    if "time_unseeded" not in args.defaults:
        torrents = [
            t
            for t in torrents
            if args.time_unseeded(
                (consts.APPLICATION_START - t.seen_complete)
                if t.num_complete == 0 and t.seen_complete > 0
                else (
                    t.added_on
                    if t.state in ["downloading", "forceDL", "stalledDL", "uploading", "forcedUP", "stalledUP"]
                    and t.num_complete == 0
                    else 0
                )
            )
        ]
    if "time_active" not in args.defaults:
        torrents = [t for t in torrents if args.time_active(t.time_active)]
    if "time_downloading" not in args.defaults:
        torrents = [t for t in torrents if args.time_downloading(t.downloading_time)]
    if "time_seeding" not in args.defaults:
        torrents = [t for t in torrents if args.time_seeding(t.seeding_time)]
    if "priority" not in args.defaults:
        torrents = [t for t in torrents if args.priority(t.priority)]
    if "progress" not in args.defaults:
        torrents = [t for t in torrents if args.progress(t.progress)]
    if "downloaded" not in args.defaults:
        torrents = [t for t in torrents if args.downloaded(t.downloaded)]
    if "uploaded" not in args.defaults:
        torrents = [t for t in torrents if args.uploaded(t.uploaded)]
    if "downloaded_session" not in args.defaults:
        torrents = [t for t in torrents if args.downloaded_session(t.downloaded_session)]
    if "uploaded_session" not in args.defaults:
        torrents = [t for t in torrents if args.uploaded_session(t.uploaded_session)]
    if "remaining" not in args.defaults:
        torrents = [t for t in torrents if args.remaining(t.amount_left)]

    if args.no_tagged:
        tags = set(args.no_tagged)
        torrents = [t for t in torrents if tags.isdisjoint(t.tags.split(", "))]
    if args.tagged:
        tags = set(args.tagged)
        torrents = [t for t in torrents if tags.issubset(t.tags.split(", "))]
    if args.torrent_search:
        torrents = [
            t
            for t in torrents
            if strings.glob_match_all(
                args.torrent_search,
                [t.name, t.comment, t.save_path if t.state_enum.is_complete else t.download_path, t.hash],
            )
        ]
    if args.torrent_exclude:
        torrents = [
            t
            for t in torrents
            if not strings.glob_match_any(
                args.torrent_exclude,
                [t.name, t.comment, t.save_path if t.state_enum.is_complete else t.download_path, t.hash],
            )
        ]
    if args.torrent_include:
        torrents = [
            t
            for t in torrents
            if strings.glob_match_any(
                args.torrent_include,
                [t.name, t.comment, t.save_path if t.state_enum.is_complete else t.download_path, t.hash],
            )
        ]
    if args.file_search:
        torrents = [t for t in torrents if strings.glob_match_all(args.file_search, [f.name for f in t.files])]
    if args.file_exclude:
        torrents = [t for t in torrents if not strings.glob_match_any(args.file_exclude, [f.name for f in t.files])]

    if args.tracker:
        trackers = set(args.tracker)
        torrents = [t for t in torrents if t.tracker_domain() in trackers]
    if args.no_tracker:
        trackers = set(args.no_tracker)
        torrents = [t for t in torrents if t.tracker_domain() not in trackers]

    if args.any_exists is not None:
        torrents = [
            t
            for t in torrents
            if args.any_exists
            is any(
                (Path(t.save_path if t.state_enum.is_complete else t.download_path) / f.name).exists() for f in t.files
            )
        ]
    if args.all_exists is not None:
        torrents = [
            t
            for t in torrents
            if args.all_exists
            is all(
                (Path(t.save_path if t.state_enum.is_complete else t.download_path) / f.name).exists() for f in t.files
            )
        ]
    if args.opened is not None:
        torrents = [
            t
            for t in torrents
            if args.opened
            is any(
                file_utils.is_file_open(Path(t.save_path if t.state_enum.is_complete else t.download_path) / f.name)
                for f in t.files
            )
        ]

    if args.timeout_size:
        torrents = [t for t in torrents if not processes.sizeout(args.timeout_size, t.total_size)]
        # reset sizeout for check during --move
        processes.sizeout_max = None
        processes.sizeout_total = 0

    return torrents


def filter_torrents(args, torrents):
    torrents = filter_torrents_by_activity(args, torrents)
    torrents = filter_torrents_by_criteria(args, torrents)

    if args.limit and not "a" in args.print:
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
        if msg in ["This torrent is private"]:
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
                "files": (sum(len(t.files) for t in tracker_torrents) if args.file_counts else None),  # a bit slow
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
    etas = [t.eta for t in state_torrents if t.eta < 8640000]
    if not etas:
        etas = [
            t.total_size / t.upspeed
            for t in state_torrents
            if t.state_enum.is_complete and t.upspeed and t.upspeed > 500
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
        "files": (sum(len(t.files) for t in state_torrents) if args.file_counts else None),
        "size": strings.file_size(sum(t.total_size for t in state_torrents)),
        "downloaded": strings.file_size(downloaded) if downloaded else None,
        "uploaded": strings.file_size(uploaded) if uploaded else None,
        "remaining": strings.file_size(remaining) if remaining else None,
        "next_eta": strings.duration_short(min(etas)) if etas else None,
        "median_eta": strings.duration_short(statistics.median(etas)) if etas else None,
        "downloaded_session": strings.file_size(downloaded_session) if downloaded_session else None,
        "uploaded_session": strings.file_size(uploaded_session) if uploaded_session else None,
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


def torrents_info():
    args = parse_args()

    def shorten(s, width):
        return s if args.verbose >= consts.LOG_INFO else strings.shorten(s, width)

    qbt_client = torrents_start.start_qBittorrent(args)
    torrents = qbt_client.torrents_info()
    qbt_enhance_torrents(qbt_client, torrents)

    if args.errored and args.trackers:
        tbl = defaultdict(lambda: {"count": 0})
        for t in torrents:
            if t.is_active and not args.verbose >= consts.LOG_INFO:
                continue

            for tr, msg in get_error_messages(t):
                tracker = fqdn_from_url(tr.url)
                tbl[(tracker, msg)]["count"] += 1
        if tbl:
            print(f"Error Torrents ({sum(data['count'] for data in tbl.values())})")

            table_data = []
            for (tracker, msg), data in tbl.items():
                table_data.append({"tracker": tracker, "msg": msg, "count": data["count"]})
            printing.table(sorted(table_data, key=lambda d: (d["msg"], d["count"], d["tracker"])))
            print()

    error_torrents = [t for t in torrents if t.state_enum.is_errored]
    if error_torrents:
        args.status = True

    reverse_sort = False
    if args.sort and args.sort.startswith("-"):
        args.sort = args.sort[1:]
        reverse_sort = True

    if args.sort == "priority":
        torrents = sorted(torrents, key=lambda t: t.priority, reverse=reverse_sort)
    elif args.sort == "ratio":
        torrents = sorted(torrents, key=lambda t: t.ratio, reverse=reverse_sort)
    elif args.sort == "remaining":
        torrents = sorted(torrents, key=lambda t: t.amount_left, reverse=reverse_sort)
    elif args.sort in ["counts", "count"]:
        torrents = sorted(torrents, key=lambda t: len(t.files), reverse=reverse_sort)
    elif args.sort in ["size", "total_size"]:
        torrents = sorted(torrents, key=lambda t: t.total_size, reverse=reverse_sort)
    elif args.sort in ["avg_size"]:
        torrents = sorted(torrents, key=lambda t: mean([f.size for f in t.files]), reverse=reverse_sort)
    elif args.sort in ["network", "download+upload", "ingress+egress"]:
        torrents = sorted(
            torrents,
            key=lambda t: (
                t.downloaded if not t.state_enum.is_complete else t.uploaded,
                t.downloaded_session if not t.state_enum.is_complete else t.uploaded_session,
            ),
            reverse=reverse_sort,
        )
    elif args.sort in ["download", "ingress"]:
        torrents = sorted(torrents, key=lambda t: (t.downloaded, t.downloaded_session), reverse=reverse_sort)
    elif args.sort in ["upload", "egress"]:
        torrents = sorted(torrents, key=lambda t: (t.uploaded, t.uploaded_session), reverse=reverse_sort)
    elif args.inactive:
        torrents = sorted(
            torrents,
            key=lambda t: (
                not t.state_enum.is_complete,
                t.eta if t.eta < 8640000 else 0,
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

    torrents = filter_torrents(args, torrents)

    if args.print and "a" in args.print:
        interesting_states = [
            # 'uploading',
            "activeUP",
            "inactiveUP",
            "queuedUP",
            "stoppedUP",
            # "downloading",
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
        for t in torrents:
            state = t.state
            if state not in interesting_states:
                if t.state_enum.is_complete:
                    state = "activeUP" if t.uploaded_session > 0 else "inactiveUP"
                else:
                    state = "activeDL" if t.downloaded_session > 0 else "inactiveDL"
            torrents_by_state.setdefault(state, []).append(t)

        categories = []
        for state, state_torrents in torrents_by_state.items():
            categories.append(agg_torrents_state(args, state, state_torrents))

        categories = sorted(categories, key=lambda d: (iterables.safe_index(interesting_states, d["state"])))
        if len(categories) > 1:
            categories.append(agg_torrents_state(args, "total", torrents))

        printing.table(iterables.list_dict_filter_bool(categories))
        print()

        if args.trackers:
            print_torrents_by_tracker(args, torrents)

    elif args.print:
        for t in torrents:
            if t.state_enum.is_complete:
                base_paths = [t.save_path, t.content_path, t.download_path]
            else:
                base_paths = [t.download_path, t.content_path, t.save_path]

            base_path = None
            for test_path in base_paths:
                if test_path and ((Path(test_path) / t.name).exists() or (Path(test_path) / t.files[0].name).exists()):
                    base_path = test_path
                    break

            if base_path is None:
                base_path = t.save_path if t.state_enum.is_complete else t.download_path
            if base_path is None:
                base_path = t.content_path
            if base_path is None:
                log.warning("%s files do not exist", t.name)
                continue

            if "f" in args.print:
                for f in t.files:
                    file_path = Path(base_path) / f.name
                    print(file_path)
            else:
                print(Path(base_path) / t.name)

    else:
        inactive_torrents = [t for t in torrents if t.is_inactive]
        if inactive_torrents:
            print(f"Inactive Torrents ({len(inactive_torrents)})")

            def gen_row(t):
                d = {
                    "name": shorten(t.name, 35),
                    "num_seeds": f"{t.num_seeds} ({t.num_complete})",
                    "progress": strings.percent(t.progress),
                    "seen_complete": (strings.relative_datetime(t.seen_complete) if t.seen_complete > 0 else ""),
                    "last_activity": strings.relative_datetime(t.last_activity),
                }
                if args.status or args.verbose >= consts.LOG_INFO:
                    d |= {"state": t.state}

                if not t.state_enum.is_complete:
                    d |= {
                        "duration": strings.duration_short(t.downloading_time),
                        "downloaded": strings.file_size(t.downloaded),
                        "remaining": strings.file_size(t.amount_left) if t.amount_left > 0 else None,
                    }
                if t.state_enum.is_complete:
                    d |= {
                        "duration": strings.duration_short(t.seeding_time),
                        "uploaded": strings.file_size(t.uploaded),
                    }

                if args.sizes or args.avg_sizes or args.move or (args.sort and "size" in args.sort):
                    d |= {"size": strings.file_size(t.total_size)}

                if args.sort == "priority":
                    d |= {"priority": str(t.priority) + (" [F]" if t.force_start else "")}
                if args.trackers:
                    d |= {"tracker": t.tracker_domain()}

                if args.file_search:
                    files = t.files
                    files = [f for f in t.files if strings.glob_match_all(args.file_search, [f.name])]

                    print(t.name)
                    printing.extended_view(files)
                    print()

                    d |= {"files": f"{len(files)} ({len(t.files)})"}
                elif args.file_counts:
                    d |= {"files": len(t.files)}

                if args.paths:
                    if t.state_enum.is_complete:
                        d |= {"path": t.save_path}
                    else:
                        d |= {"path": t.download_path}

                if args.verbose >= consts.LOG_INFO:
                    d |= {
                        "completed_on": strings.relative_datetime(t.completion_on) if t.completion_on > 0 else None,
                        "added_on": strings.relative_datetime(t.added_on) if t.added_on > 0 else None,
                        "comment": t.comment,
                        "download_path": t.download_path,
                        "save_path": t.save_path,
                        "content_path": t.content_path,
                    }

                return d

            printing.table(iterables.conform([gen_row(t) for t in inactive_torrents]))
            print()

        active_torrents = [t for t in torrents if t.is_active]
        if active_torrents:
            print(f"Active Torrents ({len(active_torrents)})")

            def gen_row(t):
                d = {
                    "name": shorten(t.name, 35),
                    "num_seeds": f"{t.num_seeds} ({t.num_complete})",
                    "progress": strings.percent(t.progress),
                }
                if args.status or args.verbose >= consts.LOG_INFO:
                    d |= {"state": t.state}

                if not t.state_enum.is_complete:
                    d |= {
                        "duration": strings.duration_short(t.downloading_time),
                        "session": strings.file_size(t.downloaded_session),
                        "remaining": strings.file_size(t.amount_left) if t.amount_left > 0 else None,
                        "speed": strings.file_size(t.dlspeed) + "/s" if t.dlspeed else None,
                        "eta": strings.duration_short(t.eta) if t.eta < 8640000 else None,
                    }
                if t.state_enum.is_complete:
                    d |= {
                        "duration": strings.duration_short(t.seeding_time),
                        "session": strings.file_size(t.uploaded_session),
                        "uploaded": strings.file_size(t.uploaded),
                        "speed": strings.file_size(t.upspeed) + "/s" if t.upspeed else None,
                        "eta": (
                            strings.duration_short(t.total_size / t.upspeed) if t.upspeed and t.upspeed > 500 else None
                        ),
                    }

                if args.sizes or args.avg_sizes or args.move or (args.sort and "size" in args.sort):
                    d |= {"size": strings.file_size(t.total_size)}

                if args.sort == "priority":
                    d |= {"priority": str(t.priority) + (" [F]" if t.force_start else "")}
                if args.trackers:
                    d |= {"tracker": t.tracker_domain()}

                if args.file_search:
                    files = t.files
                    files = [f for f in t.files if strings.glob_match_all(args.file_search, [f.name])]

                    print(t.name)
                    printing.extended_view(files)
                    print()

                    d |= {"files": f"{len(files)} ({len(t.files)})"}
                elif args.file_counts:
                    d |= {"files": len(t.files)}

                if args.paths:
                    if t.state_enum.is_complete:
                        d |= {"path": t.save_path}
                    else:
                        d |= {"path": t.download_path}

                if args.verbose >= consts.LOG_INFO:
                    d |= {
                        "seen_complete": strings.relative_datetime(t.seen_complete) if t.seen_complete > 0 else None,
                        "completed_on": strings.relative_datetime(t.completion_on) if t.completion_on > 0 else None,
                        "added_on": strings.relative_datetime(t.added_on) if t.added_on > 0 else None,
                        "last_activity": strings.relative_datetime(t.last_activity) if t.last_activity > 0 else None,
                        "comment": t.comment,
                        "download_path": t.download_path,
                        "save_path": t.save_path,
                        "content_path": t.content_path,
                    }

                return d

            printing.table(iterables.conform([gen_row(t) for t in active_torrents]))
            print()

    torrent_hashes = [t.hash for t in torrents]

    if args.tag:
        print("Tagging", len(torrents))
        qbt_client.torrents_add_tags(args.tag, torrent_hashes=torrent_hashes)
    if args.untag:
        print("Untagging", len(torrents))
        qbt_client.torrents_remove_tags(args.untag, torrent_hashes=torrent_hashes)

    if args.stop:
        print("Stopping", len(torrents))
        qbt_client.torrents_stop(torrent_hashes=torrent_hashes)

    if args.delete_incomplete:
        for t in torrents:
            # check both in case of moving failure
            if t.state_enum.is_complete:
                base_paths = [t.save_path, t.download_path]
            else:
                base_paths = [t.download_path, t.save_path]

            invalid_state = t.state.startswith("checking") or t.state in ("missingFiles", "error")
            if invalid_state:
                continue

            for file in t.files:
                for base_path in base_paths:
                    file_path = Path(base_path) / file.name
                    if file_path.exists() and not file_path.is_dir():
                        stat = file_path.stat()
                        if stat.st_blocks and stat.st_blocks > 12 and file.progress == 0.0:
                            log.warning(
                                "Skipping the rest of torrent because invalid state likely. Recheck first. %s", t.name
                            )
                            break  # invalid state likely

                        if 0.0 < file.progress < args.delete_incomplete:
                            print(f"Deleting incomplete file: {file_path}")
                            file_utils.trash(args, str(file_path), detach=False)
                        break  # Stop after deleting first valid path

    alt_move_syntax = any(
        k not in args.defaults for k in ["temp_drive", "temp_prefix", "download_drive", "download_prefix"]
    )
    if args.move or alt_move_syntax:

        def set_temp_path(t, temp_path):
            if temp_path is None:
                return

            print("      ", t.download_path, "-->", temp_path)
            qbt_client.torrents_set_download_path(str(temp_path), torrent_hashes=[t.hash])

        def set_download_path(t, download_path):
            if download_path is None:
                return

            print("      ", t.save_path, "==>", download_path)
            qbt_client.torrents_set_save_path(str(download_path), torrent_hashes=[t.hash])

        for idx, t in enumerate(torrents):
            print("Moving", idx + 1, "of", len(torrents))

            originally_stopped = bool(t.state_enum.is_stopped)
            qbt_client.torrents_stop(torrent_hashes=[t.hash])

            if "temp_drive" not in args.defaults:
                temp_path = Path(args.temp_drive)
            elif "temp_prefix" not in args.defaults:
                temp_path = Path(path_utils.mountpoint(t.download_path or t.content_path))  # keep existing drive
                log.debug("temp_path: using t.download_path %s mountpoint %s", t.download_path, temp_path)
            else:
                temp_path = args.move

            if "download_drive" not in args.defaults:
                download_path = Path(args.download_drive)
            elif "download_prefix" not in args.defaults:
                download_path = Path(path_utils.mountpoint(t.save_path or t.content_path))  # keep existing drive
                log.debug("download_path: using t.save_path %s mountpoint %s", t.save_path, download_path)
            else:
                download_path = args.move

            if temp_path:
                if not temp_path.is_absolute():  # --temp-drive or --move could be relative
                    mountpoint = path_utils.mountpoint(t.content_path)
                    temp_path = Path(mountpoint) / temp_path

                if os.path.isfile(temp_path):
                    temp_path = temp_path.parent
                elif os.path.isdir(temp_path) and path_utils.basename(temp_path) == path_utils.basename(
                    t.download_path or t.content_path
                ):
                    pass
                else:
                    if args.temp_prefix and args.temp_prefix not in temp_path.parts:
                        temp_path /= args.temp_prefix
                    if args.tracker_dirnames:
                        domain = t.tracker_domain()
                        if domain:
                            if temp_path and domain not in temp_path.parts:
                                temp_path /= domain

            if download_path:
                if not download_path.is_absolute():  # --download-drive or --move could be relative
                    mountpoint = path_utils.mountpoint(t.content_path)
                    download_path = Path(mountpoint) / download_path

                if os.path.isfile(download_path):
                    download_path = download_path.parent
                elif os.path.isdir(download_path) and path_utils.basename(download_path) == path_utils.basename(
                    t.save_path or t.content_path
                ):
                    pass
                else:
                    if args.download_prefix and args.download_prefix not in download_path.parts:
                        download_path /= args.download_prefix
                    if args.tracker_dirnames:
                        domain = t.tracker_domain()
                        if domain:
                            if download_path and domain not in download_path.parts:
                                download_path /= domain

            log.debug("temp_path %s", temp_path)
            log.debug("download_path %s", download_path)

            new_path = download_path if t.state_enum.is_complete else temp_path
            if args.simulate:
                print("Moving", t.content_path, "to", new_path)
                continue

            content_path = Path(t.content_path) if t.content_path else None
            if content_path and content_path.exists():
                if content_path.is_file():
                    print("Moving file", content_path, "to", new_path)
                    merge_mv.move(args, [str(content_path)], str(new_path))
                else:
                    new_path /= content_path.name
                    print("Moving folder", content_path, "to", new_path)
                    merge_mv.move(args, [str(content_path)], str(new_path))

            if not (args.delete_files or args.delete_rows):
                # update metadata
                if t.state_enum.is_complete:  # temp path first
                    set_temp_path(t, temp_path)
                    set_download_path(t, download_path)
                else:  # download path first
                    set_download_path(t, download_path)
                    set_temp_path(t, temp_path)

                if not originally_stopped:
                    qbt_client.torrents_start(torrent_hashes=[t.hash])

    if args.start:
        print("Starting", len(torrents))
        qbt_client.torrents_start(torrent_hashes=torrent_hashes)

    if args.force_start is not None:
        if args.force_start:
            print("Setting force-start", len(torrents))
        else:
            print("Setting normal-start", len(torrents))
        qbt_client.torrents_set_force_start(args.force_start, torrent_hashes=torrent_hashes)

    if args.download_limit is not None:
        if args.download_limit:
            print("Setting DL limit", len(torrents))
        else:
            print("Removing DL limit", len(torrents))
        qbt_client.torrents_set_download_limit(args.download_limit or -1, torrent_hashes=torrent_hashes)

    if args.upload_limit is not None:
        if args.upload_limit:
            print("Setting UP limit", len(torrents))
        else:
            print("Removing UP limit", len(torrents))
        qbt_client.torrents_set_upload_limit(args.upload_limit or -1, torrent_hashes=torrent_hashes)

    if args.check:
        print("Checking", len(torrents))
        qbt_client.torrents_recheck(torrent_hashes=torrent_hashes)

    if args.add_tracker:
        for idx, t in enumerate(torrents):
            printing.print_overwrite("Adding tracker", idx + 1, "of", len(torrents), args.add_tracker)
            qbt_client.torrents_add_trackers(t.hash, args.add_tracker)
        print()
    if args.remove_tracker:
        for idx, t in enumerate(torrents):
            printing.print_overwrite("Removing tracker", idx + 1, "of", len(torrents), args.remove_tracker)
            qbt_client.torrents_remove_trackers(t.hash, args.remove_tracker)
        print()

    if args.export:
        p = Path("exported_torrents")
        p.mkdir(exist_ok=True)
        for idx, t in enumerate(torrents):
            printing.print_overwrite("Exporting", idx + 1, "of", len(torrents), "to", p)

            file_name = f"{t.tracker_domain()}_{t.name}_{t.hash}.torrent"
            file_name = path_utils.clean_path(file_name.encode())
            (p / file_name).write_bytes(qbt_client.torrents_export(torrent_hash=t.hash))
        print()

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

    if args.wait:
        for idx, t in enumerate(torrents):
            print("Waiting for", idx + 1, "of", len(torrents), "to be one of:", ", ".join(args.wait))

            while True:
                ts = qbt_client.torrents_info(torrent_hashes=t.hash)
                if not ts:
                    log.error("Torrent %s not found %s", t.name, t.hash)
                    break
                if len(ts) > 1:
                    log.warning("More than one torrent matched %s: %s", t.hash, ts)

                t = ts[0]
                if any(map_value_status(t, status) for status in args.wait):
                    break
                sleep(3)
