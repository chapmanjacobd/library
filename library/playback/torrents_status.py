#!/usr/bin/python3

import statistics

from library import usage
from library.mediafiles import torrents_start
from library.playback import torrents_info
from library.playback.torrents_info import get_error_messages
from library.utils import arggroups, argparse_utils, consts, iterables, printing, strings


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_status)
    arggroups.qBittorrent(parser)
    arggroups.qBittorrent_torrents(parser)
    arggroups.debug(parser)

    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.qBittorrent_torrents_post(args)

    return args


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


def torrents_status():
    args = parse_args()

    def shorten(s, width):
        return s if args.verbose >= consts.LOG_INFO else strings.shorten(s, width)

    qbt_client = torrents_start.start_qBittorrent(args)
    torrents = qbt_client.torrents_info()
    torrents_info.qbt_enhance_torrents(qbt_client, torrents)

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
                "progress": strings.percent(t.progress),
                "eta": strings.duration_short(t.eta) if t.eta < 8640000 else None,
                "remaining": strings.file_size(t.amount_left) if t.amount_left > 0 else None,
                "files": len(t.files) if args.file_counts else None,
                "tracker_msg": "; ".join(msg for _tr, msg in get_error_messages(t)),
                "path": t.content_path if args.verbose >= consts.LOG_INFO else None,
            }
            for t in error_torrents
        ]
        printing.table(iterables.list_dict_filter_bool(tbl))
        print()

    torrents = torrents_info.filter_torrents(args, torrents)

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
        remaining = sum(t.amount_left for t in state_torrents)
        etas = [t.eta for t in state_torrents if t.eta < 8640000]
        dl_speed = sum(t.dlspeed for t in state_torrents)
        up_speed = sum(t.upspeed for t in state_torrents)

        categories.append(
            {
                "state": state,
                "count": len(state_torrents),
                "files": (sum(len(t.files) for t in state_torrents) if args.file_counts else None),
                "size": strings.file_size(sum(t.total_size for t in state_torrents)),
                "remaining": strings.file_size(remaining) if remaining else None,
                "dl_speed": strings.file_size(dl_speed) + "/s" if dl_speed else None,
                "up_speed": strings.file_size(up_speed) + "/s" if up_speed else None,
                "next_eta": strings.duration_short(min(etas)) if etas else None,
                "median_eta": strings.duration_short(statistics.median(etas)) if etas else None,
            }
        )

    categories = sorted(categories, key=lambda d: (iterables.safe_index(interesting_states, d["state"])))

    if len(torrents_by_state) > 1:
        remaining = sum(t.amount_left for t in torrents)
        etas = [t.eta for t in torrents if t.eta < 8640000]
        dl_speed = sum(t.dlspeed for t in torrents)
        up_speed = sum(t.upspeed for t in torrents)

        categories.append(
            {
                "state": "total",
                "count": len(torrents),
                "size": strings.file_size(sum(t.total_size for t in torrents)),
                "remaining": strings.file_size(remaining) if remaining else None,
                "dl_speed": strings.file_size(dl_speed) + "/s" if dl_speed else None,
                "up_speed": strings.file_size(up_speed) + "/s" if up_speed else None,
                "next_eta": strings.duration_short(min(etas)) if etas else None,
                "median_eta": strings.duration_short(statistics.median(etas)) if etas else None,
                "files": (sum(len(t.files) for t in torrents) if args.file_counts else None),
            }
        )
    printing.table(iterables.list_dict_filter_bool(categories))
    print()

    if args.trackers:
        print_torrents_by_tracker(args, torrents)

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
