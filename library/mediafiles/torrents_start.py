import getpass, logging, shutil, time
from contextlib import suppress
from pathlib import Path
from time import sleep

from library import usage
from library.createdb.torrents_add import get_tracker_domain, torrent_decode
from library.utils import arggroups, argparse_utils, processes
from library.utils.file_utils import trash
from library.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_start)
    arggroups.qBittorrent(parser)
    arggroups.qBittorrent_paths(parser)
    arggroups.torrents_start(parser)

    arggroups.capability_delete(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def wait_torrent_loaded(qbt_client, torrent):
    import qbittorrentapi

    info_hashes = []
    info_hashes_obj = torrent.info_hashes()
    if info_hashes_obj.has_v1():
        info_hashes.append(str(info_hashes_obj.v1))
    if info_hashes_obj.has_v2():
        info_hashes.append(str(info_hashes_obj.v2))

    attempts = 10
    attempt = 0
    while attempt < attempts:
        for info_hash in info_hashes:
            try:
                qbt_client.torrents_properties(info_hash)
                return info_hash
            except qbittorrentapi.NotFound404Error:
                sleep(0.2)
            except (qbittorrentapi.APIConnectionError, ConnectionRefusedError):
                sleep(20)

        attempt += 1
        log.info("Waiting for torrent to load in qBittorrent")
        sleep(1)
    return None


def start_qBittorrent(args):
    import qbittorrentapi

    qbt_client = qbittorrentapi.Client(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        REQUESTS_ARGS={"timeout": (5, 45)},
        HTTPADAPTER_ARGS={"pool_connections": 32, "pool_maxsize": 32},
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

    max_attempts = 500  # ~15 minutes
    attempt = 0
    while attempt < max_attempts:
        try:
            qbt_client.auth_log_in()
            log.debug("qBittorrent web UI ready")
            break
        except qbittorrentapi.LoginFailed as excinfo:
            logging.warning(f"Authentication failed. Check your qBit settings, --username, and --password: {excinfo}")
            break  # stop if authentication failing
        except (qbittorrentapi.APIConnectionError, ConnectionRefusedError):
            time.sleep(2)
            attempt += 1
    else:
        logging.error("Failed to connect to qBittorrent web UI")
        raise ConnectionError("qBittorrent web UI not available")

    return qbt_client


def torrents_start():
    args = parse_args()

    qbt_client = start_qBittorrent(args)

    if args.temp_drive and Path(args.temp_drive).is_absolute():
        temp_prefix = Path(args.temp_drive)
    else:
        temp_prefix = Path(args.download_drive)
    temp_prefix /= args.temp_prefix
    download_prefix = Path(args.download_drive) / args.download_prefix

    for path in args.paths:
        torrent = torrent_decode(path)

        download_path = download_prefix
        temp_path = temp_prefix
        if args.tracker_dirnames:
            tracker = get_tracker_domain(torrent)
            if tracker:
                download_path /= tracker
                temp_path /= tracker

        qbt_client.torrents_add(
            torrent_files=path,
            download_path=temp_path,
            save_path=download_path,
            tags=["library"],
            use_auto_torrent_management=False,
            is_stopped=args.stop,
            add_to_top_of_queue=False,
        )

        info_hash = wait_torrent_loaded(qbt_client, torrent)
        if info_hash and not args.stop:
            qbt_client.torrents_start(info_hash)
        if info_hash and args.force_start is not None:
            qbt_client.torrents_set_force_start(args.force_start, torrent_hashes=info_hash)

        if args.delete_torrent:
            trash(args, path)

    if shutil.which("qbt_prioritize.py"):
        processes.cmd("qbt_prioritize.py", strict=False)
