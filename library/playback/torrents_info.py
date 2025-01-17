#!/usr/bin/python3
import argparse
from pathlib import Path

from library import usage
from library.mediafiles import torrents_start
from library.utils import arggroups, argparse_utils, consts, iterables, printing, strings
from library.utils.path_utils import domain_from_url


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_info)
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
    parser.add_argument("--priority", action="store_true", help="Sort by priority")
    parser.add_argument("--ratio", action="store_true", help="Sort by ratio")
    parser.add_argument("--size", action="store_true", help="Sort by data transferred")
    parser.add_argument("--remaining", action="store_true", help="Sort by remaining")

    parser.add_argument("--active", action=argparse.BooleanOptionalAction, help="Show active torrents")
    parser.add_argument("--inactive", "--dead", action=argparse.BooleanOptionalAction, help="Show inactive torrents")

    parser.add_argument(
        "--force-start", "--start", action=argparse.BooleanOptionalAction, help="Force start matching torrents"
    )
    arggroups.capability_soft_delete(parser)
    arggroups.capability_delete(parser)
    arggroups.debug(parser)

    parser.add_argument("--file-search", "-s", nargs="+", help="The file path substring to search for")

    parser.add_argument("torrent_search", nargs="*", help="The info_hash, name, or save_path substring to search for")
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    if args.torrent_search or args.file_search:
        if set(["active", "inactive"]).issubset(args.defaults.keys()):
            args.active = True
            args.inactive = True
    else:
        if set(["active", "inactive"]).issubset(args.defaults.keys()):
            args.active = True

    return args


def qbt_get_tracker(qbt_client, torrent):
    tracker = torrent.tracker
    if not tracker:
        tracker = iterables.safe_unpack(
            tr.url for tr in qbt_client.torrents_trackers(torrent.hash) if tr.url.startswith("http")
        )
    return domain_from_url(tracker)


def filter_torrents_by_activity(args, torrents):
    if args.downloading and args.uploading:
        torrents = [t for t in torrents if t.downloaded_session > 0 and t.uploaded_session > 0]
    else:
        if args.active:
            torrents = [
                t
                for t in torrents
                if (t.state_enum.is_downloading and t.downloaded_session > 0)
                or (t.state_enum.is_uploading and t.uploaded_session > 0)
            ]
        if args.inactive:
            torrents = [
                t
                for t in torrents
                if (t.state_enum.is_downloading and t.downloaded_session == 0)
                or (t.state_enum.is_uploading and t.uploaded_session == 0)
            ]

        if args.downloading:
            torrents = [t for t in torrents if t.state_enum.is_downloading]
        elif args.uploading:
            torrents = [t for t in torrents if t.state_enum.is_uploading]

    return torrents


def torrents_info():
    args = parse_args()

    def shorten(s, width):
        return s if args.verbose >= consts.LOG_INFO else strings.shorten(s, width)

    qbt_client = torrents_start.start_qBittorrent(args)
    torrents = qbt_client.torrents_info()

    error_torrents = [t for t in torrents if t.state in ["missingFiles", "error"]]
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

    if args.torrent_search or args.file_search:
        torrents = [t for t in torrents if strings.glob_match(args.torrent_search, [t.name, t.save_path, t.hash])]

        if args.file_search:
            torrents = [t for t in torrents if strings.glob_match(args.file_search, [f.name for f in t.files])]
    else:
        torrents = filter_torrents_by_activity(args, torrents)

    if args.priority:
        torrents = sorted(torrents, key=lambda t: t.priority)
    elif args.ratio:
        torrents = sorted(torrents, key=lambda t: t.ratio)
    elif args.remaining:
        torrents = sorted(torrents, key=lambda t: t.amount_left)
    elif args.size:
        torrents = sorted(
            torrents,
            key=lambda t: (
                t.downloaded if t.state_enum.is_downloading else t.uploaded,
                t.downloaded_session if t.state_enum.is_downloading else t.uploaded_session,
            ),
        )
    elif args.inactive:
        torrents = sorted(
            torrents,
            key=lambda t: (
                t.state_enum.is_downloading,
                t.eta if t.eta < 8640000 else 0,
                t.time_active * t.last_activity,
            ),
        )
    else:
        torrents = sorted(
            torrents,
            key=lambda t: (
                t.state_enum.is_downloading,
                t.eta,
                t.completion_on,
                t.added_on,
            ),
        )

    if args.torrent_search or args.file_search:
        print(len(torrents), "matching torrents")

    active_torrents = [
        t
        for t in torrents
        if (t.state_enum.is_downloading and t.downloaded_session > 0)
        or (t.state_enum.is_uploading and t.uploaded_session > 0)
    ]
    if active_torrents:
        print("Active Torrents")

        def gen_row(t):
            d = {
                "name": shorten(t.name, 35),
                "num_seeds": f"{t.num_seeds} ({t.num_complete})",
                "progress": strings.safe_percent(t.progress),
            }
            if t.state_enum.is_downloading:
                d |= {
                    "downloaded_session": strings.file_size(t.downloaded_session),
                    "remaining": strings.file_size(t.amount_left) if t.amount_left > 0 else None,
                    "speed": strings.file_size(t.dlspeed) + "/s" if t.dlspeed else None,
                    "eta": strings.duration_short(t.eta) if t.eta < 8640000 else None,
                }
            if t.state_enum.is_uploading:
                d |= {
                    "uploaded_session": strings.file_size(t.uploaded_session),
                    "uploaded": strings.file_size(t.uploaded),
                }
            if args.file_search:
                files = t.files
                files = [f for f in t.files if strings.glob_match(args.file_search, [f.name])]

                print(t.name)
                printing.extended_view(files)
                print()

                d |= {"files": f"{len(files)} ({len(t.files)})"}
            elif args.file_counts:
                d |= {"files": len(t.files)}

            if args.verbose >= consts.LOG_INFO:
                d |= {
                    "tracker": qbt_get_tracker(qbt_client, t),
                    "seen_complete": (strings.relative_datetime(t.seen_complete) if t.seen_complete > 0 else None),
                    "added_on": strings.relative_datetime(t.added_on),
                    "last_activity": strings.relative_datetime(t.last_activity),
                    "size": strings.file_size(t.total_size),
                    "comment": t.comment,
                    "download_path": t.download_path,
                    "save_path": t.save_path,
                    "content_path": t.content_path,
                }

            return d

        printing.table(iterables.conform([gen_row(t) for t in active_torrents]))
        print()

    inactive_torrents = [
        t
        for t in torrents
        if (t.state_enum.is_downloading and t.downloaded_session == 0)
        or (t.state_enum.is_uploading and t.uploaded_session == 0)
    ]
    if inactive_torrents:
        print("Inactive Torrents")

        def gen_row(t):
            d = {
                "name": shorten(t.name, 35),
                "num_seeds": f"{t.num_seeds} ({t.num_complete})",
                "progress": strings.safe_percent(t.progress),
                "seen_complete": (strings.relative_datetime(t.seen_complete) if t.seen_complete > 0 else ""),
                "last_activity": strings.relative_datetime(t.last_activity),
                "time_active": strings.duration_short(t.time_active),
            }
            if t.state_enum.is_downloading:
                d |= {
                    "downloaded": strings.file_size(t.downloaded),
                    "remaining": strings.file_size(t.amount_left) if t.amount_left > 0 else None,
                }
            if t.state_enum.is_uploading:
                d |= {
                    "uploaded": strings.file_size(t.uploaded),
                }

            if args.file_search:
                files = t.files
                files = [f for f in t.files if strings.glob_match(args.file_search, [f.name])]

                print(t.name)
                printing.extended_view(files)
                print()

                d |= {"files": f"{len(files)} ({len(t.files)})"}
            elif args.file_counts:
                d |= {"files": len(t.files)}

            if args.verbose >= consts.LOG_INFO:
                d |= {
                    "state": t.state,
                    "tracker": qbt_get_tracker(qbt_client, t),
                    "added_on": strings.relative_datetime(t.added_on),
                    "size": strings.file_size(t.total_size),
                    "remaining": strings.file_size(t.amount_left),
                    "comment": t.comment,
                    "download_path": t.download_path,
                    "save_path": t.save_path,
                    "content_path": t.content_path,
                }

            return d

        printing.table(iterables.conform([gen_row(t) for t in inactive_torrents]))
        print()

    torrent_hashes = [t.hash for t in torrents]
    if args.mark_deleted:
        print("Marking deleted", len(torrents))
        qbt_client.torrents_add_tags(tags="library-delete", torrent_hashes=torrent_hashes)
    elif args.delete_files:
        print("Deleting files of", len(torrents))
        qbt_client.torrents_delete(delete_files=True, torrent_hashes=torrent_hashes)
    elif args.delete_rows:
        print("Deleting from qBit", len(torrents))
        qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent_hashes)

    if args.force_start is not None:
        print("Force-starting", len(torrents))
        qbt_client.torrents_set_force_start(args.force_start, torrent_hashes=torrent_hashes)

    if args.temp_drive and Path(args.temp_drive).is_absolute():
        temp_prefix = Path(args.temp_drive)
    else:
        temp_prefix = Path(args.download_drive)
    temp_prefix /= args.temp_prefix
    download_prefix = Path(args.download_drive) / args.download_prefix

    if "download_drive" not in args.defaults or "download_prefix" not in args.defaults:
        print("Setting save path", len(torrents))
        for t in torrents:
            download_path = download_prefix
            if args.tracker_dirnames:
                domain = qbt_get_tracker(qbt_client, t)
                if domain:
                    download_path /= domain

            print(t.save_path, "==>", download_path)
            qbt_client.torrents_set_save_path(download_path, torrent_hashes=torrent_hashes)

    if "temp_drive" not in args.defaults or "temp_prefix" not in args.defaults:
        print("Setting temp path", len(torrents))
        for t in torrents:
            temp_path = temp_prefix
            if args.tracker_dirnames:
                domain = qbt_get_tracker(qbt_client, t)
                if domain:
                    temp_path /= domain

            print(t.download_path, "==>", temp_path)
            qbt_client.torrents_set_download_path(temp_path, torrent_hashes=torrent_hashes)
