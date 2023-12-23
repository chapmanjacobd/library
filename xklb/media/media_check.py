
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fractions
import json
import shlex
import subprocess

import ffmpeg
from xklb import usage

from xklb.utils import consts, file_utils, objects, printing, nums
from xklb.utils.log_utils import log


def media_check() -> None:
    parser = argparse.ArgumentParser(prog="library media-check", usage=usage.media_check)
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

    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_path = {
            pool.submit(sample_hash_file, path, threads=args.threads, gap=args.gap, chunk_size=args.chunk_size): path
            for path in args.paths
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                file_hash_hex = future.result()
                print(file_hash_hex, shlex.quote(path), sep="\t")
            except Exception as e:
                print(f"Error hashing {path}: {e}")


def calculate_corruption(args, path, duration):
    corruption = None
    if args.check_corrupt and args.check_corrupt > 0.0:
        if args.check_corrupt >= 100.0 and args.profile != consts.DBType.video:
            try:
                output = ffmpeg.input(path).output("/dev/null", f="null")
                ffmpeg.run(output, quiet=True)
            except ffmpeg.Error:
                log.warning(f"Data corruption found. {path}")
                if args.delete_corrupt and not consts.PYTEST_RUNNING:
                    file_utils.trash(path)
        else:
            if args.check_corrupt >= 100.0:
                corruption = decode_full_scan(path)
            else:
                corruption = decode_quick_scan(path, *nums.cover_scan(duration, args.check_corrupt))

            DEFAULT_THRESHOLD = 0.02
            if corruption > DEFAULT_THRESHOLD:
                log.warning(f"Data corruption found ({corruption:.2%}). {path}")
            if args.delete_corrupt and corruption > args.delete_corrupt and not consts.PYTEST_RUNNING:
                file_utils.trash(path)
    return corruption


def decode_quick_scan(path, scans, scan_duration=3):
    fail_count = 0
    for scan in scans:
        try:
            output = ffmpeg.input(path, ss=scan).output("/dev/null", t=scan_duration, f="null")
            ffmpeg.run(output, quiet=True)
            # ffmpeg -xerror ?
            # I wonder if something like this would be faster: ffmpeg -ss 01:48:00 -i in.mp4 -map 0:v:0 -filter:v "select=eq(pict_type\,I)" -frames:v 1 out.jpg
        except ffmpeg.Error:
            fail_count += 1

    return fail_count / len(scans)


def decode_full_scan(path):
    ffprobe_cmd = [
        "ffprobe",
        "-show_entries",
        "stream=r_frame_rate,nb_read_frames,duration",
        "-select_streams",
        "v",
        "-count_frames",
        "-of",
        "json",
        "-threads",
        "5",
        "-v",
        "0",
        path,
    ]

    ffprobe = subprocess.Popen(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = ffprobe.communicate()
    data = json.loads(output)["streams"][0]

    r_frame_rate = fractions.Fraction(data["r_frame_rate"])
    nb_frames = int(data["nb_read_frames"])
    metadata_duration = float(data["duration"])
    actual_duration = nb_frames * r_frame_rate.denominator / r_frame_rate.numerator

    difference = abs(actual_duration - metadata_duration)
    average_duration = (actual_duration + metadata_duration) / 2
    percent_diff = difference / average_duration

    if difference > 0.1:
        log.warning(
            f"Metadata {printing.seconds_to_hhmmss(metadata_duration).strip()} does not match actual duration {printing.seconds_to_hhmmss(actual_duration).strip()} (diff {difference:.2f}s) {path}",
        )

    return percent_diff
