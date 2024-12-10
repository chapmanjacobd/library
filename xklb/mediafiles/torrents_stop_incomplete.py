import argparse, os, shutil
from pathlib import Path

from xklb import usage
from xklb.mediafiles.torrents_start import start_qBittorrent
from xklb.utils import arggroups, consts, devices, iterables, path_utils, printing, strings
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser(usage=usage.torrents_stop_incomplete)
    arggroups.qBittorrent(parser)
    arggroups.capability_soft_delete(parser)
    arggroups.capability_delete(parser)
    arggroups.debug(parser)

    parser.add_argument("--min-days-stalled-download", type=int, default=30, help="Minimum days since last activity")
    parser.add_argument("--min-days-no-seeder", type=int, default=60, help="Minimum days since last complete seeder")
    parser.add_argument("--min-days-downloading", type=int, default=90, help="Minimum days active downloading")

    parser.add_argument("--move", help="Directory to move folders/files")
    args = parser.parse_args()
    return args


def filter_downloading(args, torrents):
    filtered_torrents = {}
    for t in torrents:
        # log.debug('%s %s', t.name, t.seen_complete)

        if -1 < t.last_activity <= (86400 * args.min_days_stalled_download):
            status = "recent_activity"
        elif -1 < (consts.now() - t.seen_complete) <= (86400 * args.min_days_no_seeder):
            status = "recent_seeder"
        elif t.time_active <= (86400 * args.min_days_downloading):
            status = "insufficient_download_time"
        else:
            status = "ready"
        filtered_torrents.setdefault(status, []).append(t)
    return filtered_torrents


def torrents_stop_incomplete():
    args = parse_args()

    qbt_client = start_qBittorrent(args)

    torrents = qbt_client.torrents_info(tag="xklb")
    torrents = sorted(torrents, key=lambda t: -t.added_on)

    states = ["queuedDL", "forcedDL", "stalledDL", "downloading", "forcedMetaDL", "metaDL"]
    downloading = [t for t in torrents if t.state in states]

    downloading_results = filter_downloading(args, downloading)
    tbl = [
        {
            "download_status": status.replace("_", " ").title(),
            "count": len(torrents),
        }
        for status, torrents in downloading_results.items()
    ]
    printing.table(tbl)
    print()

    torrents = downloading_results.get("ready")
    if not torrents:
        return
    torrent_hashes = [t.hash for t in torrents]

    print("Ready to stop:")
    tbl = [
        {
            "progress": strings.safe_percent(t.progress),
            "size": strings.file_size(t.size),
            "remaining": strings.file_size(t.amount_left),
            "state": t.state,
            "name": t.name,
        }
        for t in torrents
    ]
    printing.table(tbl)

    if not (args.no_confirm or devices.confirm("Continue?")):
        return

    qbt_client.torrents_stop(torrent_hashes=torrent_hashes)

    if args.mark_deleted:
        qbt_client.torrents_add_tags(tags="xklb-delete", torrent_hashes=torrent_hashes)
    elif args.delete_files:
        qbt_client.torrents_delete(delete_files=True, torrent_hashes=torrent_hashes)
        return  # nothing else can be done

    # by default, delete files that are mostly incomplete
    for torrent in torrents:
        if torrent.progress == 0 or not os.path.exists(torrent.content_path):
            continue

        if os.path.isfile(torrent.content_path):
            if torrent.progress < 0.73:
                Path(torrent.content_path).unlink(missing_ok=True)
        else:
            assert torrent.root_path

            for file in torrent.files:
                path = Path(torrent.root_path) / file.name
                if file.progress < 0.73:
                    path.unlink(missing_ok=True)

    for torrent in torrents:
        if args.move and os.path.exists(torrent.content_path):
            new_path = Path(args.move)
            if not new_path.is_absolute():
                new_path = Path(path_utils.mountpoint(torrent.content_path)) / new_path

            if args.tracker_dirnames:
                tracker = torrent.tracker
                if not tracker:
                    tracker = iterables.safe_unpack(
                        tr.url for tr in qbt_client.torrents_trackers(torrent.hash) if tr.url.startswith("http")
                    )
                if tracker:
                    domain = path_utils.domain_from_url(tracker)
                    new_path /= domain

            new_path.mkdir(parents=True, exist_ok=True)
            log.info("Moving %s to %s", torrent.content_path, new_path)
            shutil.move(torrent.content_path, new_path)

        if args.delete_rows:
            qbt_client.torrents_delete(delete_files=False, torrent_hashes=torrent.hash)
