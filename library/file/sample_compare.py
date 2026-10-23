import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from library import usage
from library.file import sample_hash
from library.utils import arggroups, argparse_utils, consts
from library.utils.log_utils import log
from library.utils.shell_utils import gen_paths

MIN_COMPARE_PATHS = 2


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.sample_compare)
    arggroups.sample_hash_bytes(parser)
    parser.add_argument("--ignore-holes", "--ignore-sparse", action="store_true")
    parser.add_argument("--skip-full-hash", action="store_true")
    arggroups.debug(parser)
    parser.set_defaults(same_file_threads=4)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

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


def _get_existing_path_stats(paths):
    path_stats = {}
    existing_paths = []
    for path in paths:
        try:
            path_stats[path] = Path(path).stat()
            existing_paths.append(path)
        except FileNotFoundError:
            log.error("File not found %s", path)
    if len(existing_paths) < MIN_COMPARE_PATHS:
        raise ValueError("Not enough paths. Include 2 or more paths to compare")
    return path_stats, existing_paths


def _same_file_stat(path_stats, stat_attr, message, value_suffix):
    sizes = [getattr(stat_res, stat_attr) for stat_res in path_stats.values()]
    if all(size == sizes[0] for size in sizes):
        return True

    sorted_paths = sorted(path_stats.items(), key=lambda x: getattr(x[1], stat_attr))
    paths_str = "\n".join([f"{getattr(st, stat_attr)} {value_suffix}\t{path}" for path, st in sorted_paths])
    log.error("File %s do not match:\n%s", message, paths_str)
    return False


def _sample_hashes(existing_paths, threads, gap, chunk_size):
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            path: pool.submit(sample_hash.sample_hash_file, path, threads=threads, gap=gap, chunk_size=chunk_size)
            for path in existing_paths
        }

    paths_dict = {}
    for path, future in futures.items():
        result = future.result()
        if result:
            paths_dict[path] = result
    sorted_paths = sorted(paths_dict.items(), key=lambda x: x[1])
    paths_str = "\n".join([f"{file_hash}\t{path}" for path, file_hash in sorted_paths])
    return paths_dict, paths_str


def sample_cmp(*paths, threads=1, gap=0.1, chunk_size=None, ignore_holes=False, skip_full_hash=False):
    path_stats, existing_paths = _get_existing_path_stats(paths)
    if not _same_file_stat(path_stats, "st_size", "apparent-sizes", "bytes"):
        return False
    if not ignore_holes and consts.NOT_WINDOWS and not _same_file_stat(path_stats, "st_blocks", "holes", "blocks"):
        return False

    paths_dict, paths_str = _sample_hashes(existing_paths, threads, gap, chunk_size)
    hashes = list(paths_dict.values())
    is_equal = all(s == hashes[0] for s in hashes)
    if is_equal:
        if skip_full_hash:
            log.info("Files might be equal:\n%s", paths_str)
        elif full_hash_compare(existing_paths):
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
        threads=args.same_file_threads,
        gap=args.gap,
        chunk_size=args.chunk_size,
        ignore_holes=args.ignore_holes,
        skip_full_hash=args.skip_full_hash,
    )

    if not is_equal:
        raise SystemExit(1)
