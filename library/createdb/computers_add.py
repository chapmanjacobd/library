import concurrent.futures, json, os
from pathlib import Path

from library import usage
from library.mediadb import db_media, db_playlists
from library.utils import arggroups, argparse_utils, consts, db_utils, objects, remote_processes
from library.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.computers_add)
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("--ignore-mounts", nargs="+", default=[], help="List of mountpoints to ignore")
    parser.add_argument("hostnames", nargs="+", help="List of hostnames to connect to")
    args = parser.parse_args()
    arggroups.args_post(args, parser, create_db=True)

    args.ignore_mounts = [s.rstrip(os.sep) for s in args.ignore_mounts]
    return args


def gather_system_info(hostname):
    import paramiko

    with paramiko.SSHClient() as ssh:
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        ssh.connect(hostname)

        tempdir = remote_processes.ssh_tempdir(ssh) or "."
        library_dir = os.path.join(tempdir, "library")
        r = remote_processes.cmd(ssh, "mkdir", "-p", library_dir)

        with ssh.open_sftp() as sftp:
            src = Path(__file__).parent / "computer_info.py"
            dst = Path(library_dir) / "computer_info.py"
            sftp.put(bytes(src), bytes(dst))

        r = remote_processes.cmd(ssh, "python3", dst)
        data = json.loads(r.stdout)
        return data
    raise RuntimeError


def log_warning_if_same_free_space(computer_info, disks):
    seen_free_spaces = set()
    seen_devices = set()
    for i, disk in enumerate(disks):
        device = disk["device"]
        if device in seen_devices:
            log.warning(
                "Skipping already seen device %s... any bind mounts? %s",
                device,
                [d for d in disks if d["device"] == device],
            )
            continue
        seen_devices.add(device)

        free_space = disk["free"]
        if free_space in seen_free_spaces:
            log.warning(
                "%s mount %s has the same free space as another disk! You are lucky! Or not and you should open a ticket with this info: %s",
                computer_info["node"],
                disk["path"],
                [d for d in disks if d["free"] == free_space],
            )
        else:
            seen_free_spaces.add(free_space)


def computer_add(args, hostnames):
    import paramiko.ssh_exception

    with concurrent.futures.ThreadPoolExecutor() as ex:
        future_to_hostname = {ex.submit(gather_system_info, hostname): hostname for hostname in hostnames}

        for future in concurrent.futures.as_completed(future_to_hostname):
            hostname = future_to_hostname[future]
            try:
                computer_info = future.result()
            except (TimeoutError, paramiko.ssh_exception.NoValidConnectionsError):
                log.error("Unable to connect to %s", hostname)
            except Exception:
                log.exception(hostname)
                if args.verbose >= consts.LOG_DEBUG:
                    raise
            else:
                disks = computer_info.pop("disks")
                log.debug(computer_info)

                disks = [d for d in disks if d["path"] not in args.ignore_mounts]
                log_warning_if_same_free_space(computer_info, disks)

                computer_info["path"] = hostname
                playlists_id = db_playlists._add(args, objects.dict_filter_bool(computer_info))

                # remove ghost disks
                with args.db.conn:
                    args.db["media"].delete_where("playlists_id = ?", [playlists_id])

                for disk in disks:
                    disk = disk | {"playlists_id": playlists_id}
                    args.db["media"].insert(disk, pk=["playlists_id", "path"], alter=True, replace=True)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def computers_add():
    args = parse_args()

    db_playlists.create(args)
    db_media.create(args)

    computer_add(args, args.hostnames)
