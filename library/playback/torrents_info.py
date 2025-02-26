#!/usr/bin/python3
import argparse, getpass, os, shutil
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from library import usage
from library.mediafiles import torrents_start
from library.utils import arggroups, argparse_utils, consts, iterables, nums, path_utils, printing, processes, strings
from library.utils.path_utils import domain_from_url, fqdn_from_url


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
    parser.add_argument("--move", help="Directory to move folders/files")
    parser.add_argument("--start", action=argparse.BooleanOptionalAction, help="Start matching torrents")
    parser.add_argument("--force-start", action=argparse.BooleanOptionalAction, help="Force start matching torrents")
    parser.add_argument("--check", "--recheck", action="store_true", help="Check matching torrents")
    parser.add_argument("--export", action="store_true", help="Export matching torrent files")

    arggroups.capability_soft_delete(parser)
    arggroups.capability_delete(parser)
    arggroups.debug(parser)

    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.qBittorrent_torrents_post(args)

    if args.move and not (args.stop or args.delete_rows or args.delete_files):
        processes.exit_error("--move requires --stop or --delete-rows")

    return args


def qbt_get_tracker(qbt_client, torrent):
    tracker = torrent.tracker
    if not tracker:
        tracker = iterables.safe_unpack(
            sorted(
                (tr.url for tr in qbt_client.torrents_trackers(torrent.hash) if tr.url.startswith("http")), reverse=True
            )
        )
    return domain_from_url(tracker)


def is_active(t):
    return (not t.state_enum.is_complete and t.downloaded_session > 0) or (
        t.state_enum.is_complete and t.uploaded_session > 0
    )


def is_inactive(t):
    return (not t.state_enum.is_complete and t.downloaded_session == 0) or (
        t.state_enum.is_complete and t.uploaded_session == 0
    )


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

    if args.downloading and args.uploading:
        return [t for t in torrents if t.downloaded_session > 0 and t.uploaded_session > 0]

    if args.downloading:
        torrents = [t for t in torrents if not t.state_enum.is_complete]
    elif args.uploading:
        torrents = [t for t in torrents if t.state_enum.is_complete]
    if args.active:
        torrents = [t for t in torrents if is_active(t)]
    if args.inactive:
        torrents = [t for t in torrents if is_inactive(t)]

    return torrents


def filter_torrents_by_criteria(args, torrents):
    if "sizes" not in args.defaults:
        torrents = [t for t in torrents if args.sizes(t.total_size)]
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
        torrents = [t for t in torrents if t.eta and t.eta < 8640000 and args.time_remaining(t.eta)]
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
    if "priority" not in args.defaults:
        torrents = [t for t in torrents if args.priority(t.priority)]
    if "progress" not in args.defaults:
        torrents = [t for t in torrents if args.progress(t.progress)]
    if "uploaded" not in args.defaults:
        torrents = [t for t in torrents if args.uploaded(t.uploaded)]
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
            t for t in torrents if strings.glob_match(args.torrent_search, [t.name, t.comment, t.content_path, t.hash])
        ]
    if args.file_search:
        torrents = [t for t in torrents if strings.glob_match(args.file_search, [f.name for f in t.files])]

    if args.timeout_size:
        torrents = [t for t in torrents if not processes.sizeout(args.timeout_size, t.total_size)]

    return torrents


def filter_torrents(args, torrents):
    torrents = filter_torrents_by_activity(args, torrents)
    torrents = filter_torrents_by_criteria(args, torrents)

    if args.limit:
        torrents = torrents[: args.limit]

    if not torrents:
        processes.no_media_found()
    if args.torrent_search or args.file_search:
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


def torrents_info():
    args = parse_args()

    def shorten(s, width):
        return s if args.verbose >= consts.LOG_INFO else strings.shorten(s, width)

    qbt_client = torrents_start.start_qBittorrent(args)
    torrents = qbt_client.torrents_info()

    if args.trackers:
        tbl = defaultdict(lambda: {"count": 0})
        for t in torrents:
            if is_active(t) and not args.verbose >= consts.LOG_INFO:
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

    torrents = filter_torrents(args, torrents)

    if args.sort == "priority":
        torrents = sorted(torrents, key=lambda t: t.priority)
    elif args.sort == "ratio":
        torrents = sorted(torrents, key=lambda t: t.ratio)
    elif args.sort == "remaining":
        torrents = sorted(torrents, key=lambda t: t.amount_left)
    elif args.sort in ["counts", "count"]:
        torrents = sorted(torrents, key=lambda t: len(t.files))
    elif args.sort in ["size", "total_size"]:
        torrents = sorted(torrents, key=lambda t: t.total_size)
    elif args.sort in ["avg_size"]:
        torrents = sorted(torrents, key=lambda t: mean([f.size for f in t.files]))
    elif args.sort in ["network", "download+upload", "ingress+egress"]:
        torrents = sorted(
            torrents,
            key=lambda t: (
                t.downloaded if not t.state_enum.is_complete else t.uploaded,
                t.downloaded_session if not t.state_enum.is_complete else t.uploaded_session,
            ),
        )
    elif args.sort in ["download", "ingress"]:
        torrents = sorted(torrents, key=lambda t: (t.downloaded, t.downloaded_session))
    elif args.sort in ["upload", "egress"]:
        torrents = sorted(torrents, key=lambda t: (t.uploaded, t.uploaded_session))
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

    inactive_torrents = [t for t in torrents if is_inactive(t)]
    if inactive_torrents:
        print(f"Inactive Torrents ({len(inactive_torrents)})")

        def gen_row(t):
            d = {
                "name": shorten(t.name, 35),
                "num_seeds": f"{t.num_seeds} ({t.num_complete})",
                "progress": strings.safe_percent(t.progress),
                "seen_complete": (strings.relative_datetime(t.seen_complete) if t.seen_complete > 0 else ""),
                "last_activity": strings.relative_datetime(t.last_activity),
                "time_active": strings.duration_short(t.time_active),
            }
            if not t.state_enum.is_complete:
                d |= {
                    "downloaded": strings.file_size(t.downloaded),
                    "remaining": strings.file_size(t.amount_left) if t.amount_left > 0 else None,
                }
            if t.state_enum.is_complete:
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

            if args.sort == "priority":
                d |= {"priority": str(t.priority) + (" [F]" if t.force_start else "")}
            if args.trackers:
                d |= {"tracker": qbt_get_tracker(qbt_client, t)}
            if args.status:
                d |= {"state": t.state}
            if args.sizes or args.avg_sizes or "size" in args.sort:
                d |= {"size": strings.file_size(t.total_size)}
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

    active_torrents = [t for t in torrents if is_active(t)]
    if active_torrents:
        print(f"Active Torrents ({len(active_torrents)})")

        def gen_row(t):
            d = {
                "name": shorten(t.name, 35),
                "num_seeds": f"{t.num_seeds} ({t.num_complete})",
                "progress": strings.safe_percent(t.progress),
            }
            if not t.state_enum.is_complete:
                d |= {
                    "downloaded_session": strings.file_size(t.downloaded_session),
                    "remaining": strings.file_size(t.amount_left) if t.amount_left > 0 else None,
                    "speed": strings.file_size(t.dlspeed) + "/s" if t.dlspeed else None,
                    "eta": strings.duration_short(t.eta) if t.eta < 8640000 else None,
                }
            if t.state_enum.is_complete:
                d |= {
                    "time_active": strings.duration_short(t.time_active),
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

            if args.sort == "priority":
                d |= {"priority": str(t.priority) + (" [F]" if t.force_start else "")}
            if args.trackers:
                d |= {"tracker": qbt_get_tracker(qbt_client, t)}
            if args.status:
                d |= {"state": t.state}
            if args.sizes or args.avg_sizes or "size" in args.sort:
                d |= {"size": strings.file_size(t.total_size)}
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

            if os.path.isfile(t.content_path):
                file_name = os.path.basename(t.content_path)
                for base_path in base_paths:
                    file_path = Path(base_path) / file_name
                    if file_path.exists():
                        if t.progress < args.delete_incomplete:
                            print(f"Deleting incomplete torrent: {file_path}")
                            file_path.unlink(missing_ok=True)
                        break  # Stop after deleting first valid path
            else:
                for file in t.files:
                    for base_path in base_paths:
                        file_path = Path(base_path) / file.name
                        if file_path.exists():
                            if file.progress < args.delete_incomplete:
                                print(f"Deleting incomplete file: {file_path}")
                                file_path.unlink(missing_ok=True)
                            break  # Stop after deleting first valid path

    if (args.stop or args.delete_rows or args.delete_files) and args.move:
        print("Moving", len(torrents))
        for t in torrents:
            if os.path.exists(t.content_path):
                new_path = Path(args.move)
                if not new_path.is_absolute():
                    mountpoint = path_utils.mountpoint(t.content_path)
                    if mountpoint in ("/home", "/var/home"):
                        user = getpass.getuser()
                        mountpoint = f"{mountpoint}/{user}"

                    new_path = Path(mountpoint) / new_path

                if args.tracker_dirnames:
                    domain = qbt_get_tracker(qbt_client, t)
                    if domain:
                        new_path /= domain

                new_path.mkdir(parents=True, exist_ok=True)
                print("Moving", t.content_path, "to", new_path)
                shutil.move(t.content_path, new_path)
    else:
        if args.temp_drive and Path(args.temp_drive).is_absolute():
            temp_prefix = Path(args.temp_drive)
        else:
            temp_prefix = Path(args.download_drive)
        temp_prefix /= args.temp_prefix
        download_prefix = Path(args.download_drive) / args.download_prefix

        if "temp_drive" not in args.defaults or "temp_prefix" not in args.defaults:
            print("Setting temp path", len(torrents))
            for t in torrents:
                temp_path = temp_prefix
                if args.tracker_dirnames:
                    domain = qbt_get_tracker(qbt_client, t)
                    if domain:
                        temp_path /= domain

                print(t.download_path, "==>", temp_path)
                qbt_client.torrents_set_download_path(temp_path, torrent_hashes=[t.hash])

        if "download_drive" not in args.defaults or "download_prefix" not in args.defaults:
            print("Setting save path", len(torrents))
            for t in torrents:
                download_path = download_prefix
                if args.tracker_dirnames:
                    domain = qbt_get_tracker(qbt_client, t)
                    if domain:
                        download_path /= domain

                print(t.save_path, "==>", download_path)
                qbt_client.torrents_set_save_path(download_path, torrent_hashes=[t.hash])

    if args.start is not None:
        print("Starting", len(torrents))
        qbt_client.torrents_start(torrent_hashes=torrent_hashes)

    if args.force_start is not None:
        print("Force-starting", len(torrents))
        qbt_client.torrents_set_force_start(args.force_start, torrent_hashes=torrent_hashes)

    if args.check:
        print("Checking", len(torrents))
        qbt_client.torrents_recheck(torrent_hashes=torrent_hashes)

    if args.export:
        print("Exporting", len(torrents))
        p = Path("exported_torrents")
        p.mkdir(exist_ok=True)
        for idx, t in enumerate(torrents):
            printing.print_overwrite("Exporting", idx + 1, "of", len(torrents), "to", p)

            file_name = f"{qbt_get_tracker(qbt_client, t)}_{t.name}_{t.hash}.torrent"
            file_name = path_utils.clean_path(file_name.encode())
            (p / file_name).write_bytes(qbt_client.torrents_export(torrent_hash=t.hash))

    if args.mark_deleted:
        print("Marking deleted", len(torrents))
        qbt_client.torrents_add_tags(tags="library-delete", torrent_hashes=torrent_hashes)
    elif args.delete_files:
        print("Deleting files of", len(torrents))
        qbt_client.torrents_delete(delete_files=True, torrent_hashes=torrent_hashes)
    elif args.delete_rows:
        print("Deleting from qBit", len(torrents))
        qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent_hashes)
