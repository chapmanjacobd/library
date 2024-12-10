import argparse, os, shutil
from pathlib import Path

from xklb import usage
from xklb.mediafiles.torrents_start import start_qBittorrent
from xklb.utils import arggroups, consts, devices, iterables, nums, path_utils, printing
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser(usage=usage.torrents_stop)
    arggroups.qBittorrent(parser)
    arggroups.capability_soft_delete(parser)
    arggroups.capability_delete(parser)
    arggroups.debug(parser)

    parser.add_argument("--min-size", type=nums.human_to_bytes, default="5MiB", help="Minimum download size")
    parser.add_argument("--min-days-stalled-seed", type=int, default=45, help="Minimum days since last activity")
    parser.add_argument("--min-seeders", type=int, default=5, help="Minimum current seeders")
    parser.add_argument("--min-days-seeding", type=int, default=180, help="Minimum days seed time")

    parser.add_argument("--move", help="Directory to move folders/files")

    args = parser.parse_args()
    return args


def filter_seeding(args, torrents):
    filtered_torrents = {}
    for t in torrents:
        if t.total_size <= args.min_size:
            status = "small_size"
        elif (consts.now() - t.last_activity) <= (86400 * args.min_days_stalled_seed):
            status = "recent_activity"
        elif t.num_complete <= args.min_seeders:
            status = "few_seeders"
        elif t.time_active <= (86400 * args.min_days_seeding):
            status = "insufficient_seed_time"
        else:
            status = "ready"
        filtered_torrents.setdefault(status, []).append(t)
    return filtered_torrents


def torrents_stop():
    args = parse_args()

    qbt_client = start_qBittorrent(args)

    torrents = qbt_client.torrents_info(tag="xklb")
    torrents = sorted(torrents, key=lambda t: -t.added_on)

    states = ["queuedUP", "forcedUP", "stalledUP", "uploading"]
    seeding = [t for t in torrents if t.state in states]

    seeding_results = filter_seeding(args, seeding)
    printing.table(
        [
            {
                "seeding_status": status.replace("_", " ").title(),
                "count": len(torrents),
            }
            for status, torrents in seeding_results.items()
        ]
    )
    print()

    torrents = seeding_results.get("ready")
    if not torrents:
        return
    torrent_hashes = [t.hash for t in torrents]

    if not (args.no_confirm or devices.confirm("Continue?")):
        return

    qbt_client.torrents_stop(torrent_hashes=torrent_hashes)

    if args.mark_deleted:
        qbt_client.torrents_add_tags(tags="xklb-delete", torrent_hashes=torrent_hashes)
    elif args.delete_files:
        qbt_client.torrents_delete(delete_files=True, torrent_hashes=torrent_hashes)
        return  # nothing else can be done

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
