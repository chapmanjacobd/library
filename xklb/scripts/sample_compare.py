import argparse
from concurrent.futures import ThreadPoolExecutor
from os import stat_result
from pathlib import Path
from typing import Dict

from xklb import usage
from xklb.scripts import sample_hash
from xklb.utils import objects
from xklb.utils.log_utils import log


def sample_cmp(*paths, threads=1, gap=0.1, chunk_size=None):
    if len(paths) < 2:
        raise ValueError("Not enough paths. Include 2 or more paths to compare")

    path_stats: Dict[str, stat_result] = {}
    for path in paths:
        file_stats = Path(path).stat()
        path_stats[path] = file_stats

    sizes = [stat_res.st_size for stat_res in path_stats.values()]
    if not all(size == sizes[0] for size in sizes):
        log.error("File sizes don't match: %s", {path: st.st_size for path, st in path_stats.items()})
        raise SystemExit(4)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            path: pool.submit(sample_hash.sample_hash_file, path, threads=threads, gap=gap, chunk_size=chunk_size)
            for path in paths
        }
    paths = {}
    for path, future in futures.items():
        paths[path] = future.result()

    hashes = [hash for hash in paths.values()]
    is_equal = all(hash == hashes[0] for hash in hashes)
    if is_equal:
        log.info("Files equal: %s", paths)
    else:
        log.error("Files not equal: %s", paths)

    return is_equal


def sample_compare() -> None:
    parser = argparse.ArgumentParser(prog="library sample-compare", usage=usage.sample_compare)
    parser.add_argument("--threads", default=1, const=10, nargs="?")
    parser.add_argument(
        "--chunk-size",
        type=int,
        help="Chunk size in bytes (default is 1%%~0.2%% dependent on file size). If set, recommended to use at least 1048576 (for performance)",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=0.1,
        help="Width between chunks to skip (default 0.1 (10%%)). Values greater than 1 are treated as number of bytes",
    )
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    log.info(objects.dict_filter_bool(args.__dict__))

    is_equal = sample_cmp(*args.paths, threads=args.threads, gap=args.gap, chunk_size=args.chunk_size)

    if not is_equal:
        raise SystemExit(1)
