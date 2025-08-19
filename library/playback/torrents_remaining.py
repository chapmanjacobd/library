#!/usr/bin/python3

import os, shutil, statistics

from natsort import natsorted

from library import usage
from library.mediafiles import torrents_start
from library.playback import torrents_info
from library.utils import arggroups, argparse_utils, consts, iterables, path_utils, printing, strings
from library.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_remaining)
    arggroups.qBittorrent(parser)
    arggroups.qBittorrent_torrents(parser)
    parser.add_argument("--depth", "-d", type=int, help="Folder depth of simulated mountpoint")
    arggroups.debug(parser)

    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.qBittorrent_torrents_post(args)

    return args


def get_mountpoint(args, content_path):
    if args.depth is None:
        while not os.path.exists(content_path):
            log.debug("%s does not exist", content_path)
            content_path = os.path.dirname(content_path)
        return path_utils.mountpoint(content_path)
    elif args.depth == 0:
        if consts.IS_WINDOWS:
            return os.path.splitdrive(content_path)[0] or "\\"
        else:
            return "/"

    content_path = content_path.replace("/var", "", 1)
    parts = os.path.normpath(content_path).split(os.sep)
    if consts.IS_WINDOWS:
        drive = os.path.splitdrive(content_path)[0]
        if not drive:
            return "\\"
        parts = parts[1:]  # remove first empty element and drive letter
        return os.path.join(drive, *parts[: args.depth])
    else:
        return "/" + os.path.join(*parts[: args.depth + 1])


def torrents_remaining():
    args = parse_args()

    qbt_client = torrents_start.start_qBittorrent(args)
    torrents = qbt_client.torrents_info()
    torrents_info.qbt_enhance_torrents(qbt_client, torrents)

    torrents = torrents_info.filter_torrents(args, torrents)
    torrents = natsorted(torrents, key=lambda t: t.content_path)

    torrents_by_mountpoint = {}
    for t in torrents:
        mountpoint = get_mountpoint(args, t.content_path)
        torrents_by_mountpoint.setdefault(mountpoint, []).append(t)

    categories = []
    for mountpoint, mountpoint_torrents in torrents_by_mountpoint.items():
        used = sum(t.total_size - t.amount_left for t in mountpoint_torrents)
        remaining = sum(t.amount_left for t in mountpoint_torrents)
        etas = [t.eta for t in mountpoint_torrents if t.eta < 8640000]
        wasted = sum(t.properties.total_wasted for t in mountpoint_torrents)
        dl_speed = sum(t.dlspeed for t in mountpoint_torrents if not t.state_enum.is_complete)
        dl_time = [t.downloading_time for t in mountpoint_torrents if t.state_enum.is_complete]

        categories.append(
            {
                "mountpoint": mountpoint,
                "count": len(mountpoint_torrents),
                "files": (sum(len(t.files) for t in mountpoint_torrents) if args.file_counts else None),
                "size": strings.file_size(sum(t.total_size for t in mountpoint_torrents)),
                "used": strings.file_size(used) if used else None,
                "wasted": strings.file_size(wasted) if wasted else None,
                "remaining": strings.file_size(remaining) if remaining else None,
                "free": strings.file_size(shutil.disk_usage(mountpoint).free) if args.depth is None else None,
                "unallocated_free": (
                    strings.file_size(shutil.disk_usage(mountpoint).free - remaining)
                    if remaining and args.depth is None
                    else None
                ),
                "dl_speed": strings.file_size(dl_speed) + "/s" if dl_speed else None,
                "historical_eta": strings.duration_short(statistics.median(dl_time)) if dl_time else None,
                "next_eta": strings.duration_short(min(etas)) if etas else None,
                "median_eta": strings.duration_short(statistics.median(etas)) if etas else None,
            }
        )
    printing.table(iterables.list_dict_filter_bool(categories))
