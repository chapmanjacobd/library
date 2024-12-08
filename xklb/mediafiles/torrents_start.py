import getpass, hashlib, logging, shutil, time
from contextlib import suppress
from pathlib import Path
from time import sleep

from xklb import usage
from xklb.createdb.torrents_add import get_tracker
from xklb.utils import arggroups, argparse_utils, processes
from xklb.utils.file_utils import trash
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_start)
    arggroups.qBittorrent(parser)
    arggroups.capability_delete(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def wait_torrent_loaded(qbt_client, torrent):
    import qbittorrentapi
    from torrentool.api import Bencode

    v1_info_hash = hashlib.sha1(Bencode.encode(torrent._struct.get("info"))).hexdigest()
    v2_info_hash = hashlib.sha256(Bencode.encode(torrent._struct.get("info"))).hexdigest()

    attempts = 120
    attempt = 0
    while attempt < attempts:
        with suppress(qbittorrentapi.NotFound404Error):
            qbt_client.torrents_properties(v1_info_hash)
            return v1_info_hash

        with suppress(qbittorrentapi.NotFound404Error):
            qbt_client.torrents_properties(v2_info_hash)
            return v2_info_hash

        attempt += 1
        log.info("Waiting for torrent to load in qBittorrent")
        sleep(1)


def start_qBittorrent(args):
    import qbittorrentapi

    qbt_client = qbittorrentapi.Client(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
    )

    with suppress(Exception):
        qbt_client.auth_log_in()
        return qbt_client

    if shutil.which("qbittorrent-nox"):
        username = getpass.getuser()
        processes.cmd("sudo", "systemctl", "enable", "--now", f"qbittorrent-nox@{username}.service")
    else:
        processes.cmd("setsid", "-f", "qbittorrent")

    log.info("Waiting for qBittorrent web UI to load")

    max_attempts = 2500  # ~20 minutes
    attempt = 0
    while attempt < max_attempts:
        try:
            qbt_client.auth_log_in()
            log.debug("qBittorrent web UI ready")
            break
        except qbittorrentapi.LoginFailed as e:
            logging.warning(f"Authentication failed. Check your qBit settings, --username, and --password: {e}")
            break  # stop if authentication failing
        except (qbittorrentapi.APIConnectionError, ConnectionRefusedError):
            time.sleep(0.5)
            attempt += 1
    else:
        logging.error("Failed to connect to qBittorrent web UI")
        raise ConnectionError("qBittorrent web UI not available")

    return qbt_client


def torrents_start():
    args = parse_args()

    from torrentool.api import Torrent

    qbt_client = start_qBittorrent(args)

    if args.dl_limit:  # type: ignore
        current_count = qbt_client.torrents_count()
        max_active_uploads = current_count + 5000

        qbt_client.app_set_preferences(
            {
                "preallocate_all": True,
                "dl_limit": args.dl_limit,
                "up_limit": args.up_limit,
                "max_active_downloads": 1,
                "max_active_uploads": max_active_uploads,
                "max_active_torrents": max_active_uploads + 1,
                "max_active_checking_torrents": 3,
                "slow_torrent_inactive_timer": 80,
                # divide by 10 but also some bps -> kbps BS
                "slow_torrent_dl_rate_threshold": (args.dl_limit) // 10000,  # type: ignore
                "slow_torrent_ul_rate_threshold": (args.up_limit or args.dl_limit) // 10000,  # type: ignore
            }
        )

    if args.temp_drive and Path(args.temp_drive).is_absolute():
        temp_prefix = Path(args.temp_drive)
    else:
        temp_prefix = Path(args.download_drive)
    temp_prefix /= args.temp_prefix
    download_prefix = Path(args.download_drive) / args.download_prefix

    for path in args.paths:
        torrent = Torrent.from_file(path)

        download_path = download_prefix
        temp_path = temp_prefix
        if args.tracker_dirnames:
            tracker = get_tracker(torrent)
            download_path /= tracker
            temp_path /= tracker

        qbt_client.torrents_add(
            torrent_files=path,
            download_path=temp_path,
            save_path=download_path,
            tags=["xklb"],
            use_auto_torrent_management=False,
            is_stopped=False,
            add_to_top_of_queue=False,
        )

        info_hash = wait_torrent_loaded(qbt_client, torrent)
        qbt_client.torrents_start(info_hash)

        if args.delete_torrent:
            trash(args, path)
