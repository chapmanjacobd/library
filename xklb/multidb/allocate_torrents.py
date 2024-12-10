import getpass, os, sqlite3

import humanize
import pandas as pd

from xklb import usage
from xklb.tablefiles import mcda
from xklb.utils import (
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    devices,
    iterables,
    nums,
    printing,
    processes,
    remote_processes,
    sqlgroups,
    strings,
)
from xklb.utils.file_utils import trash
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.allocate_torrents)
    arggroups.sql_fs(parser)
    parser.set_defaults(fts=False)

    parser.add_argument(
        "--min-free-space", type=nums.human_to_bytes, default="50GiB", help="Skip disks that do not have enough space"
    )
    parser.add_argument("--max-io-rate", type=nums.human_to_bytes, default="100MiB", help="Skip disks that are busy")

    arggroups.qBittorrent(parser)
    parser.add_argument(
        "--dl-limit",
        "--download-limit",
        type=str,
        help="Download limit. If set then a few additional global preferences will also be changed",
    )
    parser.add_argument("--up-limit", "--ul-limit", "--upload-limit", type=str, help="Upload limit")

    arggroups.debug(parser)

    parser.add_argument("computer_database")
    arggroups.database(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    return args


downloaded_torrents = set()


def gen_torrent_matches(torrents, available_space):
    for torrent in torrents:
        if torrent["size"] < available_space and torrent["path"] not in downloaded_torrents:
            available_space -= torrent["size"]
            downloaded_torrents.add(torrent["path"])
            yield torrent


def allocate_torrents():
    args = parse_args()

    import paramiko

    computer_db = db_utils.connect(args, conn=sqlite3.connect(args.computer_database))

    disks = list(
        computer_db.query(
            """
            SELECT
                computers.path host,
                disks.path mountpoint,
                disks.free,
                disks.total
            FROM media AS disks
            JOIN playlists AS computers ON computers.id = disks.playlists_id
            WHERE free >= :min_free_space
            AND (device_read_5min + device_write_5min) /(5*60) /2 <= :max_io_rate
            ORDER BY free
            """,
            {
                "min_free_space": args.min_free_space,
                "max_io_rate": args.max_io_rate,
            },
        )
    )
    total_available = sum(d["free"] - args.min_free_space for d in disks)
    print(f"{len(disks)} disks matched. {strings.file_size(total_available)} available space")

    args.filter_sql.append("and size < :download_size")
    args.filter_bindings["download_size"] = disks[-1]["free"] - args.min_free_space

    torrents = list(args.db.query(*sqlgroups.playlists_fs_sql(args, limit=None)))
    total_size = sum(d["size"] for d in torrents)
    print(f"{len(torrents)} undownloaded torrents. {strings.file_size(total_size)} total space")
    iterables.count_category(torrents, "tracker")

    if not torrents:
        processes.no_media_found()

    torrents = mcda.sort(args, pd.DataFrame(torrents), ["size", "-tracker_count"]).to_dict(orient="records")
    torrents = torrents[: args.limit]

    for disk in disks:
        if disk["mountpoint"] in ("/home", "/var/home"):
            user = getpass.getuser()
            disk["mountpoint"] = f"{disk['mountpoint']}/{user}"

        available_space = disk["free"] - args.min_free_space
        disk["downloads"] = list(gen_torrent_matches(torrents, available_space))

    # TODO: use nvme download_dir
    # but better to chunk one drive at a time because temp download _moving_ can occur
    # at the same time as nvme save_path saving. maybe 2x buffer could work

    if args.verbose >= consts.LOG_INFO:
        for d in disks:
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

    printing.table(
        [
            {
                "host": d["host"],
                "path": d["mountpoint"],
                "total_size": humanize.naturalsize(d["total"]),
                "download_count": len(d["downloads"]),
                "unique_trackers": len(set(t["tracker"] for t in d["downloads"])),
                "before_free": strings.file_size(d["free"]),
                "download_size": strings.file_size(sum(t["size"] for t in d["downloads"])),
                "after_free": strings.file_size(d["free"] - sum(t["size"] for t in d["downloads"])),
            }
            for d in disks
        ]
    )
    print()

    total_size = sum(d["size"] for d in torrents)
    print(f"{len(torrents)} torrents allocated ({strings.file_size(total_size)})")

    if not args.print and (args.no_confirm or devices.confirm("Allocate and start downloads?")):
        for d in disks:
            torrent_files = [t["path"] for t in d["downloads"] if os.path.exists(t["path"])]
            if not torrent_files:
                continue

            with paramiko.SSHClient() as ssh:
                ssh.load_system_host_keys()
                ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
                ssh.connect(d["host"])

                remote_processes.cmd(
                    ssh,
                    "python3",
                    "-m",
                    "xklb",
                    "torrents-start",
                    *argparse_utils.forward_arggroups(
                        args,
                        arggroups.qBittorrent,
                        download_drive=d["mountpoint"],
                    ),
                    *torrent_files,
                    local_files=torrent_files,
                    # cwd="lb",  # debug
                )

            if args.delete_torrent:
                for path in torrent_files:
                    log.debug("Trashed %s", path)
                    trash(args, path, detach=False)
