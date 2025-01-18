#!/usr/bin/python3
import argparse

from library import usage
from library.mediafiles import torrents_start
from library.playback.torrents_info import filter_torrents_by_activity, qbt_get_tracker
from library.utils import arggroups, argparse_utils, consts, iterables, printing, processes, strings


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_status)
    arggroups.qBittorrent(parser)
    parser.add_argument(
        "--downloading",
        "--download",
        "--down",
        "--dl",
        "--leeching",
        "--leech",
        action="store_true",
        help="Include downloading torrents",
    )
    parser.add_argument(
        "--uploading",
        "--upload",
        "--up",
        "--ul",
        "--seeding",
        "--seeds",
        action="store_true",
        help="Include uploading torrents",
    )

    parser.add_argument(
        "--file-counts", "--files", "--counts", action="store_true", help="Print file counts (a bit slow)"
    )

    parser.add_argument("--all", action="store_true", help="Show active and inactive torrents")
    parser.add_argument("--active", action="store_true", help="Show active torrents")
    parser.add_argument("--inactive", "--dead", action="store_true", help="Show inactive torrents")

    parser.add_argument("--trackers", action=argparse.BooleanOptionalAction, default=False, help="Show tracker summary")
    arggroups.debug(parser)

    parser.add_argument("--file-search", "-s", nargs="+", help="The file path substring to search for")

    parser.add_argument("torrent_search", nargs="*", help="The info_hash, name, or save_path substring to search for")
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    if set(["active", "inactive"]).issubset(args.defaults.keys()):
        if args.all or args.torrent_search or args.file_search:
            args.active = False
            args.inactive = False

    return args


def torrents_status():
    args = parse_args()

    def shorten(s, width):
        return s if args.verbose >= consts.LOG_INFO else strings.shorten(s, width)

    qbt_client = torrents_start.start_qBittorrent(args)
    torrents = qbt_client.torrents_info()

    error_torrents = [t for t in torrents if t.state_enum.is_errored]
    error_torrents = sorted(
        error_torrents, key=lambda t: (t.amount_left == t.total_size, t.eta, t.amount_left), reverse=True
    )
    if error_torrents:
        print("Error Torrents")
        tbl = [
            {
                "state": t.state,
                "name": shorten(t.name, width=40),
                "progress": strings.safe_percent(t.progress),
                "eta": strings.duration_short(t.eta) if t.eta < 8640000 else None,
                "remaining": strings.file_size(t.amount_left) if t.amount_left > 0 else None,
                "files": len(t.files) if args.file_counts else None,
            }
            for t in error_torrents
        ]
        printing.table(tbl)
        print()

    torrents = filter_torrents_by_activity(args, torrents)

    if args.torrent_search or args.file_search:
        torrents = [t for t in torrents if strings.glob_match(args.torrent_search, [t.name, t.save_path, t.hash])]

        if args.file_search:
            torrents = [t for t in torrents if strings.glob_match(args.file_search, [f.name for f in t.files])]

    if not torrents:
        processes.no_media_found()
    print(len(torrents), "torrents:")
    print()

    torrents_by_state = {}
    for torrent in torrents:
        torrents_by_state.setdefault(torrent.state, []).append(torrent)

    categories = []
    for state, state_torrents in torrents_by_state.items():
        remaining = sum(t.amount_left for t in state_torrents)
        categories.append(
            {
                "state": state,
                "count": len(state_torrents),
                "size": strings.file_size(sum(t.total_size for t in state_torrents)),
                "remaining": strings.file_size(remaining) if remaining else None,
                "files": (sum(len(t.files) for t in state_torrents) if args.file_counts else None),
            }
        )

    interesting_states = [
        "stoppedUP",
        "queuedUP",
        "stoppedDL",
        "forcedMetaDL",
        "metaDL",
        "forcedDL",
        "stalledDL",
        # 'forcedUP', 'stalledUP', 'uploading',  # not very interesting
        "downloading",
        "missingFiles",
        "error",
    ]

    categories = sorted(
        categories,
        key=lambda d: (
            d["state"].endswith(("missingFiles", "error")),
            d["state"].endswith(("downloading", "DL")),
            iterables.safe_index(interesting_states, d["state"]),
        ),
    )
    printing.table(iterables.list_dict_filter_bool(categories))
    print()

    if args.trackers:
        torrents_by_tracker = {}
        for torrent in torrents:
            torrents_by_tracker.setdefault(qbt_get_tracker(qbt_client, torrent), []).append(torrent)

        trackers = []
        for tracker, tracker_torrents in torrents_by_tracker.items():
            tracker_torrents = [t for t in tracker_torrents if t.state not in ("stoppedDL",)]
            remaining = sum(t.amount_left for t in tracker_torrents)
            if remaining or args.file_counts:
                trackers.append(
                    {
                        "tracker": tracker,
                        "count": len(tracker_torrents),
                        "size": sum(t.total_size for t in tracker_torrents),
                        "remaining": remaining,
                        "files": (
                            sum(len(t.files) for t in tracker_torrents) if args.file_counts else None
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

    transfer = qbt_client.transfer_info()
    print(transfer.connection_status.upper())

    dl_speed = strings.file_size(transfer.dl_info_speed)
    dl_limit = f"[{strings.file_size(transfer.dl_rate_limit)}/s]" if transfer.dl_rate_limit > 0 else ""
    dl_d = strings.file_size(transfer.dl_info_data)
    print(f"DL {dl_speed}/s {dl_limit} ({dl_d})")

    up_speed = strings.file_size(transfer.up_info_speed)
    up_limit = f"[{strings.file_size(transfer.up_rate_limit)}/s]" if transfer.up_rate_limit > 0 else ""
    up_d = strings.file_size(transfer.up_info_data)
    print(f"UP {up_speed}/s {up_limit} ({up_d})")
