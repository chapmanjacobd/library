import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from xklb import usage
from xklb.scripts import sample_hash
from xklb.utils import objects
from xklb.utils.log_utils import log


def sample_cmp(*paths, threads=1, gap=0.1, chunk_size=None, ignore_holes=False):
    if len(paths) < 2:
        raise ValueError("Not enough paths. Include 2 or more paths to compare")

    path_stats = {path: Path(path).stat() for path in paths}

    sizes = [stat_res.st_size for stat_res in path_stats.values()]
    if not all(size == sizes[0] for size in sizes):
        sorted_paths = sorted(path_stats.items(), key=lambda x: x[1].st_size)
        paths_str = "\n".join([f"{st.st_size} bytes\t{path}" for path, st in sorted_paths])
        log.error("File apparent-sizes do not match:\n%s", paths_str)
        raise SystemExit(4)

    if not ignore_holes:
        sizes = [stat_res.st_blocks for stat_res in path_stats.values()]
        if not all(size == sizes[0] for size in sizes):
            sorted_paths = sorted(path_stats.items(), key=lambda x: x[1].st_blocks)
            paths_str = "\n".join([f"{st.st_blocks} blocks\t{path}" for path, st in sorted_paths])
            log.error("File holes do not match:\n%s", paths_str)
            raise SystemExit(4)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            path: pool.submit(sample_hash.sample_hash_file, path, threads=threads, gap=gap, chunk_size=chunk_size)
            for path in paths
        }
    paths = {}
    for path, future in futures.items():
        paths[path] = future.result()

    sorted_paths = sorted(paths.items(), key=lambda x: x[1])
    paths_str = "\n".join([f"{hash}\t{path}" for path, hash in sorted_paths])

    hashes = [hash for hash in paths.values()]
    is_equal = all(hash == hashes[0] for hash in hashes)
    if is_equal:
        log.info("Files might be equal:\n%s", paths_str)
    else:
        log.error("Files are not equal:\n%s", paths_str)

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
    parser.add_argument("--ignore-holes", "--ignore-sparse", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    log.info(objects.dict_filter_bool(args.__dict__))

    is_equal = sample_cmp(
        *args.paths, threads=args.threads, gap=args.gap, chunk_size=args.chunk_size, ignore_holes=args.ignore_holes
    )

    if not is_equal:
        raise SystemExit(1)
