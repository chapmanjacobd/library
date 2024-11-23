import concurrent.futures, json, os
from pathlib import Path

import paramiko

from xklb.mediadb import db_media, db_playlists
from xklb.utils import arggroups, argparse_utils, consts, objects, remote_processes
from xklb.utils.log_utils import log


def gather_system_info(hostname):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname)

    tempdir = remote_processes.ssh_tempdir(ssh) or "."
    xklb_dir = os.path.join(tempdir, "xklb")
    r = remote_processes.cmd(ssh, "mkdir", "-p", xklb_dir)

    sftp = ssh.open_sftp()
    src = Path(__file__).parent / "computer_info.py"
    dst = Path(xklb_dir) / "computer_info.py"
    sftp.put(bytes(src), bytes(dst))

    r = remote_processes.cmd(ssh, "python3", dst)
    data = json.loads(r.stdout)

    ssh.close()
    return data


def computer_add():
    parser = argparse_utils.ArgumentParser()

    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("hostnames", nargs="+", help="List of hostnames to connect to")
    args = parser.parse_args()
    arggroups.args_post(args, parser, create_db=True)

    with concurrent.futures.ThreadPoolExecutor() as ex:
        future_to_hostname = {ex.submit(gather_system_info, hostname): hostname for hostname in args.hostnames}

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

                computer_info['path'] = hostname
                playlists_id = db_playlists._add(args, objects.dict_filter_bool(computer_info))
                for disk in disks:
                    disk = disk | {"playlists_path": hostname, "playlists_id": playlists_id}
                    db_media.add(args, disk)


# min free space: 32_212_254_720  # 30 GiB
# max IO: 52_428_800  # 50 MiB/s
