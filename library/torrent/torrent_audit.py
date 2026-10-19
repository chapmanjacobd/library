import argparse
import os
from collections import defaultdict
from pathlib import Path

from library import usage
from library.torrent import torrents_info, torrents_start
from library.utils import arggroups, argparse_utils


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.torrent_audit)
    arggroups.qBittorrent(parser)
    parser.add_argument("--exclude", action="append", default=[], help="Exclude a torrent root from the audit")
    parser.add_argument("--dirs", action="store_true", help="Print scanned torrent roots")
    arggroups.debug(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)
    return args


def filesystem_files(root: Path) -> set[Path]:
    if root.is_file():
        return {root.resolve()}
    if root.is_dir():
        return {path.resolve() for path in root.rglob("*") if path.is_file()}
    return set()


def torrent_roots(torrent) -> list[Path]:
    roots = []
    for value in (torrent.save_path, torrent.download_path, torrent.content_path):
        if value:
            root = Path(os.path.realpath(value))
            if root not in roots:
                roots.append(root)
    return roots


def audit_torrents(torrents, excluded=(), file_getter=torrents_info.torrent_files):
    excluded = {Path(os.path.realpath(path)) for path in excluded}
    filesystem_paths = set()
    known_by_path = defaultdict(dict)
    scanned_roots = set()

    for torrent in torrents:
        torrent_name = str(getattr(torrent, "name", "torrent"))
        torrent_key = str(getattr(torrent, "hash", "") or id(torrent))
        roots = [root for root in torrent_roots(torrent) if root not in excluded]
        torrent_files = file_getter(torrent)

        for root in roots:
            scanned_roots.add(root)
            filesystem_paths.update(filesystem_files(root))
            for torrent_file in torrent_files:
                name = getattr(torrent_file, "name", None)
                if not name:
                    continue
                relative = Path(str(name))
                if relative.is_absolute():
                    continue
                candidate = root if root.is_file() else root / relative
                if candidate.is_file():
                    known_by_path[candidate.resolve()][torrent_key] = torrent_name

    duplicates = {
        path: set(torrent_names.values())
        for path, torrent_names in known_by_path.items()
        if len(torrent_names) > 1
    }
    orphans = sorted(filesystem_paths - set(known_by_path))
    return {
        "scanned_roots": sorted(scanned_roots),
        "duplicates": duplicates,
        "orphans": orphans,
    }


def torrent_audit() -> None:
    args = parse_args()
    qbt_client = torrents_start.start_qBittorrent(args)
    result = audit_torrents(qbt_client.torrents_info(), args.exclude)

    if args.dirs:
        for path in result["scanned_roots"]:
            print("DIRECTORY", path, sep="\t")

    duplicates = result["duplicates"]
    print(f"DUPLICATES\t{len(duplicates)}")
    for path, names in sorted(duplicates.items()):
        print("DUPLICATE", path, ", ".join(sorted(names)), sep="\t")

    orphans = result["orphans"]
    print(f"ORPHANS\t{len(orphans)}")
    for path in orphans:
        print("ORPHAN", path, sep="\t")
