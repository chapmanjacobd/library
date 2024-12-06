import argparse, os
from datetime import datetime

from xklb.mediafiles.torrents_start import start_qBittorrent
from xklb.utils import arggroups

# TODO: to stop and add the delete tag to torrents
# qbt_client.torrents_info()

# default exclude:

#   3 or less seeders
#   less than 180 days
#   inactive seeding less than 30 days
#   size less than 5MiB

# move files to to_process dir and start shrink


def torrents_stop():
    parser = argparse.ArgumentParser()
    arggroups.qBittorrent(parser)

    parser.add_argument("--process-prefix", default="/path/to/to_process", help="Directory to move processed files")
    parser.add_argument("--min_seeders", type=int, default=3, help="Minimum number of seeders")
    parser.add_argument("--min_age_days", type=int, default=180, help="Minimum age in days")
    parser.add_argument("--min_active_seeding_days", type=int, default=30, help="Minimum active seeding time in days")
    parser.add_argument(
        "--min_size_bytes", type=int, default=5 * 1024 * 1024, help="Minimum size in bytes (5 MiB by default)"
    )
    args = parser.parse_args()

    qbt_client = start_qBittorrent(args)

    torrents = qbt_client.torrents_info()

    for torrent in torrents:
        if torrent.num_complete <= args.min_seeders:
            continue

        added_on = datetime.fromtimestamp(torrent.added_on)
        if (datetime.now() - added_on).days < args.min_age_days:
            continue

        if torrent.seeding_time < args.min_active_seeding_days * 24 * 60 * 60:  # Convert days to seconds
            continue

        if torrent.size < args.min_size_bytes:
            continue

        qbt_client.torrents_pause(torrent_hashes=torrent.hash)
        qbt_client.torrents_add_tags(tags="processing", torrent_hashes=torrent.hash)

        # Move files to to_process directory
        save_path = torrent.save_path
        torrent_name = torrent.name
        new_path = os.path.join(args.to_process_dir, torrent_name)

        if os.path.exists(save_path):
            os.makedirs(args.to_process_dir, exist_ok=True)
            os.rename(save_path, new_path)

        # Start the shrink process (assuming a function or command to start shrink)
        # Example: start_shrink_process(new_path)
        print(f"Moved and started shrink process for {torrent_name}")
