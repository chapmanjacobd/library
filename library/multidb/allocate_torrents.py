import os, sqlite3

import humanize
import pandas as pd

from library import usage
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    devices,
    iterables,
    nums,
    pd_utils,
    printing,
    processes,
    remote_processes,
    sqlgroups,
    strings,
)
from library.utils.file_utils import trash
from library.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.allocate_torrents)
    arggroups.sql_fs(parser)
    parser.set_defaults(fts=False)

    parser.add_argument("--hosts", action=argparse_utils.ArgparseList, help="Limit to specific computers")
    parser.add_argument(
        "--exclude-disks",
        metavar="host:/mount",
        action=argparse_utils.ArgparseList,
        help="Exclude specific mountpoints",
    )
    parser.add_argument(
        "--min-free-space",
        type=nums.human_to_bytes,
        default="50GiB",
        help="Exclude disks that do not have enough space",
    )
    parser.add_argument("--max-io-rate", type=nums.human_to_bytes, default="100MiB", help="Exclude disks that are busy")
    parser.add_argument("--hide-unallocated", action="store_true", help="Hide unallocated disks")
    parser.add_argument("--hide-unallocatable", action="store_true", help="Hide unallocatable torrents")

    arggroups.qBittorrent(parser)
    arggroups.qBittorrent_paths(parser)
    arggroups.torrents_start(parser)

    arggroups.debug(parser)

    parser.add_argument("computer_database")
    arggroups.database(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    return args


def get_disks(args, computer_db):
    try:
        disks_columns = computer_db["media"].columns_dict
    except Exception:
        disks_columns = {}

    disks = list(
        computer_db.query(
            f"""
            SELECT
                computers.path host
                , disks.path mountpoint
                {', disks.free - coalesce(disks.allocated,0) AS free' if 'allocated' in disks_columns else ', disks.free'}
                , disks.total
            FROM media AS disks
            JOIN playlists AS computers ON computers.id = disks.playlists_id
            WHERE free >= :min_free_space
            AND (device_read_5s + device_write_5s) /(30) /2 <= :max_io_rate
            ORDER BY free
            """,
            {
                "min_free_space": args.min_free_space,
                "max_io_rate": args.max_io_rate,
            },
        )
    )
    if args.hosts:
        disks = [d for d in disks if d["host"] in args.hosts]
    if args.exclude_disks:
        disks = [
            d
            for d in disks
            if not any(s == d["mountpoint"] or s == f"{d['host']}:{d['mountpoint']}" for s in args.exclude_disks)
        ]

    return disks


def print_torrent_info(disks):
    for d in disks:
        if d["downloads"]:
            print(d["host"], d["mountpoint"])
            printing.table(
                [
                    {
                        "title": t["title"],
                        "time_uploaded": strings.relative_datetime(t["time_uploaded"]),
                        "time_created": strings.relative_datetime(t["time_created"]),
                        "size": strings.file_size(t["size"]),
                        "file_count": t["file_count"],
                        "comment": t["comment"],
                        "tracker": t["tracker"],
                    }
                    for t in d["downloads"]
                ]
            )
            print()


def print_disks(args, disks):
    printing.table(
        [
            {
                "host": d["host"],
                "path": d["mountpoint"],
                "disk_size": humanize.naturalsize(d["total"], format="%.0f"),
                "download_count": len(d["downloads"]),
                "unique_trackers": len(set(t["tracker"] for t in d["downloads"])),
                "before_free": strings.file_size(d["free"]),
                "download_size": strings.file_size(sum(t["size"] for t in d["downloads"])),
                "after_free": strings.file_size(d["free"] - sum(t["size"] for t in d["downloads"])),
            }
            for d in disks
            if not args.hide_unallocated or (args.hide_unallocated and d["downloads"])
        ]
    )
    print()


def print_torrents_by_tracker(torrents):
    torrents_by_tracker = {}
    for t in torrents:
        torrents_by_tracker.setdefault(t["tracker"], []).append(t)

    trackers = []
    for tracker, tracker_torrents in torrents_by_tracker.items():
        trackers.append(
            {
                "tracker": tracker,
                "count": len(tracker_torrents),
                "size": sum(d["size"] for d in tracker_torrents),
                "files": sum(d["file_count"] for d in tracker_torrents),
            }
        )

    trackers = sorted(trackers, key=lambda d: (d["count"] // 10, d["tracker"]))
    printing.table(
        iterables.list_dict_filter_bool(
            [
                {
                    **d,
                    "size": strings.file_size(d["size"]),
                }
                for d in trackers
            ]
        )
    )
    print()


def allocate_torrents():
    args = parse_args()

    import paramiko

    computer_db = db_utils.connect(args, conn=sqlite3.connect(args.computer_database))

    disks = get_disks(args, computer_db)

    total_available = sum(d["free"] - args.min_free_space for d in disks if d["free"] - args.min_free_space > 0)
    print(f"{len(disks)} disks matched. {strings.file_size(total_available)} available space")
    if not disks:
        raise SystemExit(28)

    if args.hide_unallocatable:
        args.filter_sql.append("and size < :download_size")
        args.filter_bindings["download_size"] = disks[-1]["free"] - args.min_free_space  # largest free disk

    torrents = list(args.db.query(*sqlgroups.playlists_fs_sql(args, limit=None)))
    total_size = sum(d["size"] for d in torrents)
    print(f"{len(torrents)} undownloaded torrents. {strings.file_size(total_size)} total space")
    iterables.list_dict_value_counts(torrents, "tracker")
    torrents = [
        d
        | {
            "is_recent_and_small": (
                d["size"] < nums.human_to_bytes("20Gi")
                and 0
                < consts.APPLICATION_START - (d["time_modified"] or d["time_created"])
                < nums.human_to_seconds("4days")
            )
        }
        for d in torrents
    ]

    if not torrents:
        processes.no_media_found()

    if "sort" in args.defaults:
        torrents = pd_utils.rank_dataframe(
            pd.DataFrame(torrents),
            {
                "size": {"direction": "desc"},
                "file_count": {},
                "is_recent_and_small": {"direction": "desc", "weight": 2},
                "time_created": {},
                "time_modified": {},
                "tracker_count": {"weight": 4},
            },
        ).to_dict(orient="records")
    torrents = torrents[: args.limit]

    downloaded_torrents = set()
    for disk in disks:
        available_space = disk["free"] - args.min_free_space

        disk["downloads"] = []
        for torrent in torrents:
            if torrent["size"] < available_space and torrent["path"] not in downloaded_torrents:
                downloaded_torrents.add(torrent["path"])
                available_space -= torrent["size"]
                disk["downloads"].append(torrent)

    # TODO: use nvme download_dir
    # but better to chunk one drive at a time because temp download _moving_ can occur
    # at the same time as nvme save_path saving. maybe 2x buffer could work

    if args.verbose >= consts.LOG_INFO:
        print_torrent_info(disks)

    allocated_torrents = [t for d in disks for t in d["downloads"]]

    print_torrents_by_tracker(allocated_torrents)
    print_disks(args, disks)

    if not allocated_torrents:
        processes.exit_error("No torrents could be allocated")

    total_size = sum(t["size"] for t in allocated_torrents)
    print(f"{len(allocated_torrents)} torrents allocated ({strings.file_size(total_size)})")

    if not args.print and (args.no_confirm or devices.confirm("Allocate and start downloads?")):
        import paramiko.ssh_exception

        for d in disks:
            torrent_files = [t["path"] for t in d["downloads"] if os.path.exists(t["path"])]
            if not torrent_files:
                continue

            try:
                with paramiko.SSHClient() as ssh:
                    ssh.load_system_host_keys()
                    ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
                    ssh.connect(d["host"])
                    setattr(ssh, "host", d["host"])

                    torrent_files_chunks = iterables.chunks(torrent_files, 128)
                    for torrent_files_chunk in torrent_files_chunks:
                        remote_processes.cmd(
                            ssh,
                            "python3",
                            "-m",
                            "library",
                            "torrents-start",
                            *argparse_utils.forward_arggroups(args, arggroups.torrents_start),
                            *argparse_utils.forward_arggroups(args, arggroups.qBittorrent),
                            *argparse_utils.forward_arggroups(
                                args,
                                arggroups.qBittorrent_paths,
                                download_drive=d["mountpoint"],
                            ),
                            *torrent_files_chunk,
                            local_files=torrent_files_chunk,
                            # cwd="lb",  # debug
                        )

                if args.delete_torrent:
                    for path in torrent_files:
                        log.debug("Trashed %s", path)
                        trash(args, path, detach=False)

            except (TimeoutError, paramiko.ssh_exception.NoValidConnectionsError):
                log.error("Unable to connect to %s", d["host"])
