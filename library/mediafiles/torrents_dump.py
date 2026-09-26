#!/usr/bin/python3

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from library import usage
from library.createdb import torrents_add
from library.utils import arggroups, argparse_utils, printing, strings


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_dump)
    arggroups.debug(parser)

    parser.add_argument("--trackers", action="store_true", help="Aggregate torrent metadata by tracker")
    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def gen_torrents(l):
    for s in l:
        p = Path(s)
        if p.is_dir():
            for file in p.rglob("*.torrent"):
                if not file.is_dir():
                    yield file
        elif p.is_file() and p.suffix == ".torrent":
            yield p


def aggregate_trackers(torrents):
    trackers = {}
    for _, torrent in torrents:
        tracker = torrent["tracker"]
        stats = trackers.setdefault(tracker, {"tracker": tracker, "count": 0, "size": 0})
        stats["count"] += 1
        stats["size"] += torrent["size"]

    return [
        {**stats, "size": strings.file_size(stats["size"])}
        for stats in sorted(trackers.values(), key=lambda d: (d["size"], d["tracker"] or ""))
    ]


def torrents_dump():
    args = parse_args()

    torrent_files = list(gen_torrents(args.paths))
    with ThreadPoolExecutor() as executor:
        metadata_results = executor.map(torrents_add.extract_metadata, torrent_files)
    torrents = list(zip(torrent_files, metadata_results))

    if args.trackers:
        tracker_stats = aggregate_trackers(torrents)
        if tracker_stats:
            printing.table(tracker_stats)
        return

    rows = []
    for torrent_path, d in torrents:
        torrent = torrents_add.torrent_decode(torrent_path)
        trackers = [t for t in torrent.trackers()]
        announce_urls = []
        for t in sorted(trackers, key=lambda t: (t.source, t.tier)):
            try:
                if url := t.url:
                    announce_urls.append(url)
            except UnicodeDecodeError:
                continue

        rows.append(
            d
            | {
                "size": strings.file_size(d["size"]),
                "size_avg": strings.file_size(d["size_avg"]),
                "size_median": strings.file_size(d["size_median"]),
                "time_uploaded": strings.relative_datetime(d["time_uploaded"]),
                "time_created": strings.relative_datetime(d["time_created"]),
                "time_modified": strings.relative_datetime(d["time_modified"]),
                "time_created": strings.relative_datetime(d["time_created"]),
                "files": d["files"][0]["path"] + ", ...",
                "announce_urls": " ".join(announce_urls),
                "web_seeds": " ".join(d["web_seeds"]),
            }
        )

    printing.table(rows)
