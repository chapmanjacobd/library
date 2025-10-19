#!/usr/bin/python3

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from library import usage
from library.createdb import torrents_add
from library.utils import arggroups, argparse_utils, printing, strings


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.torrents_dump)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def gen_torrents(l):
    for s in l:
        for file in Path(s).rglob("*.torrent"):
            if not file.is_dir():
                yield file
        else:
            file = Path(s)
            if file.is_file() and file.suffix == ".torrent":
                yield file


def torrents_dump():
    args = parse_args()

    torrent_files = list(gen_torrents(args.paths))
    with ThreadPoolExecutor() as executor:
        metadata_results = executor.map(torrents_add.extract_metadata, torrent_files)
    torrents = list(zip(torrent_files, metadata_results))

    for i, (torrent_path, d) in enumerate(torrents):
        torrent = torrents_add.torrent_decode(torrent_path)
        trackers = [t for t in torrent.trackers()]
        announce_urls = []
        for t in sorted(trackers, key=lambda t: (t.source, t.tier)):
            try:
                if url := t.url:
                    announce_urls.append(url)
            except UnicodeDecodeError:
                continue

        printing.table(
            [
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
            ]
        )
