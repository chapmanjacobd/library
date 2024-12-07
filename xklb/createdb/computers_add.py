import concurrent.futures, json, os
from pathlib import Path

from xklb import usage
from xklb.mediadb import db_playlists
from xklb.utils import arggroups, argparse_utils, consts, db_utils, objects, remote_processes
from xklb.utils.log_utils import log


def parse_args(action, usage):
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.debug(parser)

    arggroups.database(parser)
    if action == consts.SC.computers_add:
        parser.add_argument("hostnames", nargs="+", help="List of hostnames to connect to")
    args = parser.parse_args()
    arggroups.args_post(args, parser, create_db=True)
    return args


def gather_system_info(hostname):
    import paramiko

    with paramiko.SSHClient() as ssh:
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        ssh.connect(hostname)

        tempdir = remote_processes.ssh_tempdir(ssh) or "."
        xklb_dir = os.path.join(tempdir, "xklb")
        r = remote_processes.cmd(ssh, "mkdir", "-p", xklb_dir)

        with ssh.open_sftp() as sftp:
            src = Path(__file__).parent / "computer_info.py"
            dst = Path(xklb_dir) / "computer_info.py"
            sftp.put(bytes(src), bytes(dst))

        r = remote_processes.cmd(ssh, "python3", dst)
        data = json.loads(r.stdout)
        return data
    raise RuntimeError


def log_warning_if_same_free_space(computer_info, disks):
    seen_free_spaces = set()
    for i, disk in enumerate(disks):
        free_space = disk["free"]
        if free_space in seen_free_spaces:
            log.warning(
                "%s mount %s has the same free space as another disk! You should open a ticket with this info: %s",
                computer_info["path"],
                disk["path"],
                disks,
            )
        else:
            seen_free_spaces.add(free_space)


def computer_add(args, hostnames):
    with concurrent.futures.ThreadPoolExecutor() as ex:
        future_to_hostname = {ex.submit(gather_system_info, hostname): hostname for hostname in hostnames}

        for future in concurrent.futures.as_completed(future_to_hostname):
            hostname = future_to_hostname[future]
            try:
                computer_info = future.result()
            except Exception:
                log.exception(hostname)
                if args.verbose >= consts.LOG_DEBUG:
                    raise
            else:
                disks = computer_info.pop("disks")
                log.debug(computer_info)

                log_warning_if_same_free_space(computer_info, disks)

                computer_info["path"] = hostname
                playlists_id = db_playlists._add(args, objects.dict_filter_bool(computer_info))
                for disk in disks:
                    disk = disk | {"playlists_id": playlists_id}
                    args.db["media"].insert(disk, pk=["playlists_id", "path"], alter=True, replace=True)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def computers_add():
    args = parse_args(consts.SC.computers_add, usage.computers_add)

    computer_add(args, args.hostnames)


def computers_update():
    args = parse_args(consts.SC.computers_update, usage.computers_update)

    computer_add(args, [d["path"] for d in args.db.query("select path from playlists")])
