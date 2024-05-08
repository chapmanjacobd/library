import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from xklb import usage
from xklb.files import sample_hash
from xklb.utils import arggroups, argparse_utils
from xklb.utils.arg_utils import gen_paths
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(prog="library sample-compare", usage=usage.sample_compare)
    arggroups.sample_hash_bytes(parser)
    parser.add_argument("--ignore-holes", "--ignore-sparse", action="store_true")
    parser.add_argument("--skip-full-hash", action="store_true")
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.sample_hash_bytes_post(args)
    return args


def full_hash_file(path):
    sha256_hash = hashlib.sha256()

    try:
        with open(path, "rb") as file:
            for byte_block in iter(lambda: file.read(1048576), b""):
                sha256_hash.update(byte_block)
    except FileNotFoundError:
        return None

    return sha256_hash.hexdigest()


def full_hash_compare(paths):
    with ThreadPoolExecutor(max_workers=4) as pool:
        hash_results = list(pool.map(full_hash_file, paths))
    return all(x == hash_results[0] for x in hash_results)


def sample_cmp(*paths, threads=1, gap=0.1, chunk_size=None, ignore_holes=False, skip_full_hash=False):
    if len(paths) < 2:
        raise ValueError("Not enough paths. Include 2 or more paths to compare")

    path_stats = {path: Path(path).stat() for path in paths}

    sizes = [stat_res.st_size for stat_res in path_stats.values()]
    if not all(size == sizes[0] for size in sizes):
        sorted_paths = sorted(path_stats.items(), key=lambda x: x[1].st_size)
        paths_str = "\n".join([f"{st.st_size} bytes\t{path}" for path, st in sorted_paths])
        log.error("File apparent-sizes do not match:\n%s", paths_str)
        return False

    if not ignore_holes:
        sizes = [stat_res.st_blocks for stat_res in path_stats.values()]
        if not all(size == sizes[0] for size in sizes):
            sorted_paths = sorted(path_stats.items(), key=lambda x: x[1].st_blocks)
            paths_str = "\n".join([f"{st.st_blocks} blocks\t{path}" for path, st in sorted_paths])
            log.error("File holes do not match:\n%s", paths_str)
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            path: pool.submit(sample_hash.sample_hash_file, path, threads=threads, gap=gap, chunk_size=chunk_size)
            for path in paths
        }
    paths_dict = {}
    for path, future in futures.items():
        paths_dict[path] = future.result()

    sorted_paths = sorted(paths_dict.items(), key=lambda x: x[1])
    paths_str = "\n".join([f"{hash}\t{path}" for path, hash in sorted_paths])

    hashes = [hash for hash in paths_dict.values()]
    is_equal = all(hash == hashes[0] for hash in hashes)
    if is_equal:
        if skip_full_hash:
            log.info("Files might be equal:\n%s", paths_str)
        else:
            if full_hash_compare(paths):
                log.info("Files are equal:\n%s", paths_str)
            else:
                log.info("Files are similar but NOT equal:\n%s", paths_str)
    else:
        log.error("Files are not equal:\n%s", paths_str)

    return is_equal


def sample_compare() -> None:
    args = parse_args()

    paths = list(gen_paths(args))
    is_equal = sample_cmp(
        *paths,
        threads=args.threads,
        gap=args.gap,
        chunk_size=args.chunk_size,
        ignore_holes=args.ignore_holes,
        skip_full_hash=args.skip_full_hash,
    )

    if not is_equal:
        raise SystemExit(1)
