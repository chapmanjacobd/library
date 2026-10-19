import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from library import usage
from library.database.add import torrents_add
from library.utils import argparse_utils, printing, strings


@dataclass(frozen=True)
class TorrentFile:
    torrent: object
    torrent_name: str
    path: str
    size: int
    offset: int
    index: int


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.torrent_match)
    parser.add_argument("--threads", type=int, default=6, help="Number of hashing threads")
    parser.add_argument(
        "--min-pieces",
        type=int,
        default=1,
        help="Minimum number of matching pieces (default: 1)",
    )
    parser.add_argument("torrent_directory", type=Path, help="Directory containing .torrent files")
    parser.add_argument("search_directories", type=Path, nargs="+", help="Directories or files to scan")
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("--threads must be at least 1")
    if args.min_pieces < 1:
        parser.error("--min-pieces must be at least 1")
    return args


def iter_torrent_paths(path: Path):
    if path.is_file() and path.suffix == ".torrent":
        yield path
    elif path.is_dir():
        yield from (p for p in path.rglob("*.torrent") if p.is_file())
    else:
        message = f"Torrent directory or file not found: {path}"
        raise FileNotFoundError(message)


def iter_search_files(paths: list[Path]):
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (p for p in path.rglob("*") if p.is_file())
        else:
            message = f"Search path not found: {path}"
            raise FileNotFoundError(message)


def torrent_files(torrent) -> list[TorrentFile]:
    storage = torrent.files()
    torrent_name = str(torrent.name())
    return [
        TorrentFile(
            torrent=torrent,
            torrent_name=torrent_name,
            path=str(storage.file_path(index)),
            size=int(storage.file_size(index)),
            offset=int(storage.file_offset(index)),
            index=index,
        )
        for index in range(torrent.num_files())
    ]


def _piece_hash_bytes(piece_hash) -> bytes:
    if isinstance(piece_hash, bytes):
        return piece_hash
    if hasattr(piece_hash, "to_bytes"):
        return piece_hash.to_bytes()
    return bytes(piece_hash)


def contained_piece_spans(file: TorrentFile, piece_length: int, total_size: int):
    file_end = file.offset + file.size
    first_piece = (file.offset + piece_length - 1) // piece_length
    last_piece = (file_end + piece_length - 1) // piece_length

    for piece_index in range(first_piece, last_piece):
        piece_start = piece_index * piece_length
        piece_end = min(piece_start + piece_length, total_size)
        if piece_start >= file.offset and piece_end <= file_end:
            yield piece_index, piece_start - file.offset, piece_end - piece_start


def match_file(path: Path, file: TorrentFile, min_pieces: int) -> dict | None:
    torrent = file.torrent
    piece_length = int(torrent.piece_length())
    total_size = int(torrent.total_size())
    spans = list(contained_piece_spans(file, piece_length, total_size))
    if len(spans) < min_pieces:
        return None

    matches = 0
    matched_bytes = 0
    checked_bytes = 0
    with path.open("rb") as candidate:
        for piece_index, offset, length in spans:
            candidate.seek(offset)
            data = candidate.read(length)
            checked_bytes += length
            if len(data) == length and hashlib.sha1(data).digest() == _piece_hash_bytes(
                torrent.hash_for_piece(piece_index)
            ):
                matches += 1
                matched_bytes += length

    if matches < min_pieces:
        return None

    return {
        "candidate": str(path),
        "torrent": file.torrent_name,
        "torrent_file": file.path,
        "matches": matches,
        "pieces": len(spans),
        "percent": matches / len(spans) * 100,
        "matched_bytes": matched_bytes,
        "checked_bytes": checked_bytes,
        "unchecked_bytes": file.size - checked_bytes,
    }


def match_torrents(torrent_paths: list[Path], search_paths: list[Path], min_pieces: int, threads: int) -> list[dict]:
    torrents = [torrents_add.torrent_decode(path) for path in torrent_paths]
    torrent_files_by_size: dict[int, list[TorrentFile]] = {}
    for torrent in torrents:
        for file in torrent_files(torrent):
            torrent_files_by_size.setdefault(file.size, []).append(file)

    candidates_by_size: dict[int, list[Path]] = {}
    for path in iter_search_files(search_paths):
        candidates_by_size.setdefault(path.stat().st_size, []).append(path)

    jobs = [
        (candidate, torrent_file)
        for size, candidates in candidates_by_size.items()
        for candidate in candidates
        for torrent_file in torrent_files_by_size.get(size, [])
    ]
    matches = []
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {executor.submit(match_file, candidate, file, min_pieces): (candidate, file) for candidate, file in jobs}
        for future in as_completed(futures):
            candidate, file = futures[future]
            try:
                match = future.result()
            except OSError as exc:
                print(f"Error reading {candidate}: {exc}")
                continue
            if match:
                matches.append(match)
    return sorted(matches, key=lambda row: (row["torrent"], row["torrent_file"], row["candidate"]))


def print_matches(matches: list[dict]) -> None:
    for match in matches:
        print(
            f"[MATCH] {match['candidate']} <-> {match['torrent']}/{match['torrent_file']} "
            f"{match['matches']}/{match['pieces']} pieces ({match['percent']:.1f}%) "
            f"{strings.file_size(match['unchecked_bytes'])} unchecked"
        )

    progress = {}
    for match in matches:
        torrent = progress.setdefault(match["torrent"], {"matched": 0, "total": 0, "files": set()})
        torrent["matched"] += match["matched_bytes"]
        torrent["total"] += match["checked_bytes"] + match["unchecked_bytes"]
        torrent["files"].add(match["torrent_file"])

    print("\n=== Torrent Progress ===")
    rows = []
    for name, data in progress.items():
        percent = data["matched"] / data["total"] * 100 if data["total"] else 0
        rows.append(
            {
                "torrent": name,
                "percent": f"{percent:.1f}%",
                "matched": strings.file_size(data["matched"]),
                "files": len(data["files"]),
            }
        )
    printing.table(sorted(rows, key=lambda row: (-float(row["percent"].rstrip("%")), row["torrent"])))
    print(f"\n{len(progress)} torrents with at least one matching file.")


def torrent_match() -> None:
    args = parse_args()
    torrent_paths_list = sorted(iter_torrent_paths(args.torrent_directory))
    matches = match_torrents(torrent_paths_list, args.search_directories, args.min_pieces, args.threads)
    print_matches(matches)
