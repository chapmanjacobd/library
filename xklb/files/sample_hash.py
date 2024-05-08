import hashlib, shlex
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from xklb import usage
from xklb.utils import arggroups, argparse_utils, nums
from xklb.utils.arg_utils import gen_paths
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(prog="library sample-hash", usage=usage.sample_hash)
    arggroups.sample_hash_bytes(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.sample_hash_bytes_post(args)

    return args


def single_thread_read(path, segments, chunk_size):
    with open(path, "rb") as f:
        for start in segments:
            f.seek(start)
            yield f.read(chunk_size)


def open_seek_read(path, start, size):
    with open(path, "rb") as f:
        f.seek(start)
        return f.read(size)


def threadpool_read(path, segments, chunk_size, max_workers=10):
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(open_seek_read, path, start, chunk_size) for start in segments]

        for future in futures:
            yield future.result()


def sample_hash_file(path, threads=1, gap=0.1, chunk_size=None):
    try:
        file_stats = Path(path).stat()
    except FileNotFoundError:
        return None

    disk_usage = (
        file_stats.st_blocks * 512
    )  # https://github.com/python/cpython/blob/main/Doc/library/os.rst#files-and-directories
    if file_stats.st_size > disk_usage:
        log.warning(f"File has holes %s", path)

    if chunk_size is None:
        chunk_size = int(nums.linear_interpolation(file_stats.st_size, [(26214400, 262144), (52428800000, 10485760)]))

    segments = nums.calculate_segments(file_stats.st_size, chunk_size, gap)

    if threads > 1:
        data = threadpool_read(path, segments, chunk_size, max_workers=threads)
    else:
        data = single_thread_read(path, segments, chunk_size)

    file_hash = hashlib.sha256()
    for d in data:
        file_hash.update(d)
    file_hash_hex = file_hash.hexdigest()
    return file_hash_hex


def sample_hash() -> None:
    args = parse_args()

    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_path = {
            pool.submit(sample_hash_file, path, threads=args.threads, gap=args.gap, chunk_size=args.chunk_size): path
            for path in gen_paths(args)
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                file_hash_hex = future.result()
                print(file_hash_hex, shlex.quote(path), sep="\t")
            except Exception as e:
                print(f"Error hashing {path}: {e}")
