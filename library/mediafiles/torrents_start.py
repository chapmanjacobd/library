import getpass, os, shutil, time
from pathlib import Path
from time import sleep

from library import usage
from library.createdb.torrents_add import get_tracker_domain, torrent_decode
from library.utils import arggroups, argparse_utils, processes
from library.utils.log_utils import log
from library.utils.shell_utils import trash


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

    try:
        qbt_client.auth_log_in()
        return qbt_client
    except qbittorrentapi.LoginFailed:
        # qBittorrent may allow API access with WebUI authentication disabled.
        if args.username is None and args.password is None:
            return qbt_client
    except (qbittorrentapi.APIConnectionError, ConnectionRefusedError):
        pass

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
            log.warning("Authentication failed. Check your qBit settings, --username, and --password: %s", excinfo)
            break  # stop if authentication failing
        except (qbittorrentapi.APIConnectionError, ConnectionRefusedError):
            time.sleep(2)
            attempt += 1
    else:
        log.error("Failed to connect to qBittorrent web UI")
        raise ConnectionError("qBittorrent web UI not available")

    return qbt_client


def scan_torrent_location(torrent, roots, max_depth=3):
    if torrent.num_files() == 0:
        return None, None
    first_file = Path(next(iter(torrent.files())).path)
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for dirpath, dirnames, _filenames in os.walk(root):
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth > max_depth:
                dirnames[:] = []
                continue
            if (Path(dirpath) / first_file).exists():
                return root, Path(dirpath)
    return None, None


def torrent_paths(args, torrent, temp_prefix, download_prefix):
    if args.scan:
        roots = [temp_prefix, download_prefix]
        if args.tracker_dirnames:
            tracker = get_tracker_domain(torrent)
            if tracker:
                roots += [temp_prefix / tracker, download_prefix / tracker]
        root, location = scan_torrent_location(torrent, roots)
        if not location:
            return None, None
        log.debug("Found files for %s at %s (root %s)", torrent.name(), location, root)

        if root == temp_prefix or temp_prefix in root.parents:
            # files live under the temp/downloading prefix: keep them as the temp path,
            # and let the download prefix be the final save path
            return download_prefix, location
        # files live under the download/seeding prefix: use them as the final save path,
        # and the temp prefix as where any incomplete data would go
        return location, temp_prefix

    download_path = download_prefix
    temp_path = temp_prefix
    if args.tracker_dirnames:
        tracker = get_tracker_domain(torrent)
        if tracker:
            download_path /= tracker
            temp_path /= tracker
    return download_path, temp_path


def torrents_start():
    args = parse_args()

    qbt_client = start_qBittorrent(args)

    if args.temp_drive and Path(args.temp_drive).is_absolute():
        temp_drive = Path(args.temp_drive)
    else:
        temp_drive = Path(args.download_drive)

    if "download_drive" in args.defaults and args.temp_drive:
        # --temp-drive set but not --download-drive: use the same drive for both prefixes
        download_drive = temp_drive
    else:
        download_drive = Path(args.download_drive)
    temp_prefix = temp_drive / args.temp_prefix
    download_prefix = download_drive / args.download_prefix

    paths = []
    for p in args.paths:
        p = Path(p)
        if p.is_dir():
            paths.extend(p.glob("*.torrent"))
        else:
            paths.append(p)

    for path in paths:
        torrent = torrent_decode(path)

        download_path, temp_path = torrent_paths(args, torrent, temp_prefix, download_prefix)
        if download_path is None:
            log.warning(
                "Skipping %s: no file matches under %s or %s (torrent file left in place)",
                path,
                temp_prefix,
                download_prefix,
            )
            continue

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
