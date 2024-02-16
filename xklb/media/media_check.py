import argparse, fractions, json, os, shlex, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from xklb import usage
from xklb.utils import consts, file_utils, nums, objects, printing, processes, strings
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser(prog="library media-check", usage=usage.media_check)
    parser.add_argument("--threads", default=1, const=10, nargs="?")
    parser.add_argument(
        "--chunk-size",
        type=float,
        help="Chunk size in seconds (default 0.5 second). If set, recommended to use >0.1 seconds",
        default=0.5,
    )
    parser.add_argument(
        "--gap",
        default="0.05",
        help="Width between chunks to skip (default 5%%). Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument(
        "--delete-corrupt",
        help="delete media that is more corrupt or equal to this threshold. Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument(
        "--full-scan-if-corrupt",
        help="full scan as second pass if initial scan result more corruption or equal to this threshold. Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument("--full-scan", "--full", action="store_true")
    parser.add_argument("--audio-scan", "--audio", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    args.gap = nums.float_from_percent(args.gap)
    if args.delete_corrupt:
        args.delete_corrupt = nums.float_from_percent(args.delete_corrupt)
    if args.full_scan_if_corrupt:
        args.full_scan_if_corrupt = nums.float_from_percent(args.full_scan_if_corrupt)

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def decode_quick_scan(path, scans, scan_duration=3):
    def decode(scan):
        proc = processes.cmd(
            "ffmpeg",
            "-nostdin",
            "-nostats",
            "-xerror",
            "-v",
            "16",
            "-err_detect",
            "explode",
            "-ss",
            f"{scan:.2f}",
            "-i",
            path,
            "-t",
            str(scan_duration),
            "-f",
            "null",
            os.devnull,
        )
        # I wonder if something like this would be faster: -map 0:v:0 -filter:v "select=eq(pict_type\,I)" -frames:v 1
        if proc.stderr != "":
            raise RuntimeError

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(decode, scan) for scan in scans]

    fail_count = 0
    for future in futures:
        try:
            future.result()
        except RuntimeError:
            fail_count += 1

    return fail_count / len(scans)


def decode_full_scan(path, audio_scan=False, frames="frames", threads=5):
    ffprobe = processes.FFProbe(path)
    metadata_duration = ffprobe.duration or 0

    if audio_scan or not ffprobe.has_video:
        try:
            with tempfile.NamedTemporaryFile(suffix=".mkv") as temp_output:
                processes.cmd(
                    "ffmpeg",
                    "-nostdin",
                    "-nostats",
                    "-v",
                    "16",
                    "-i",
                    path,
                    "-acodec",
                    "copy",
                    "-map_metadata",
                    "-1",
                    "-y",
                    temp_output.name,
                )
                actual_duration = processes.FFProbe(temp_output.name).duration or 0
        except RuntimeError:
            actual_duration = 0
    else:
        ffprobe_cmd = [
            "ffprobe",
            "-show_entries",
            f"stream=r_frame_rate,nb_read_{frames},duration",
            "-select_streams",
            "v",
            f"-count_{frames}",
            "-of",
            "json",
            "-threads",
            str(threads),
            "-v",
            "0",
            path,
        ]

        ffprobe_frames = subprocess.Popen(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, err = ffprobe_frames.communicate()
        data = json.loads(output)["streams"][0]

        r_frame_rate = fractions.Fraction(data["r_frame_rate"])
        nb_frames = int(data.get(f"nb_read_{frames}") or 0)
        metadata_duration = ffprobe.duration or 0
        actual_duration = nb_frames * r_frame_rate.denominator / r_frame_rate.numerator

    difference = abs(actual_duration - metadata_duration)
    try:
        corruption = difference / metadata_duration
    except ZeroDivisionError:
        corruption = 0.5

    if difference > 0.1:
        log.info(
            f"Metadata {printing.seconds_to_hhmmss(metadata_duration).strip()} does not match actual duration {printing.seconds_to_hhmmss(actual_duration).strip()} (diff {difference:.2f}s)\t{path}",
        )

    return corruption


def corruption_threshold_exceeded(threshold, corruption, duration):
    if threshold:
        if 1 > threshold > 0:
            if corruption >= threshold:
                return True
        elif ((duration or 100) * corruption) >= threshold:
            return True
    return False


def calculate_corruption(
    path, chunk_size=1, gap=0.1, full_scan=False, full_scan_if_corrupt=False, audio_scan=False, threads=5
):
    if full_scan:
        if gap == 0:
            corruption = decode_full_scan(path, audio_scan=audio_scan, frames="packets", threads=threads)
        else:
            corruption = decode_full_scan(path, audio_scan=audio_scan, threads=threads)
    else:
        duration = nums.safe_int(processes.FFProbe(path).duration)
        if duration in [None, 0]:
            return 0.5
        corruption = decode_quick_scan(path, nums.calculate_segments(duration, chunk_size, gap), chunk_size)
        if corruption_threshold_exceeded(full_scan_if_corrupt, corruption, duration):
            corruption = decode_full_scan(path, audio_scan=audio_scan, threads=threads)
    return corruption


def media_check() -> None:
    args = parse_args()

    with ThreadPoolExecutor(max_workers=1 if args.verbose >= consts.LOG_DEBUG else 4) as pool:
        future_to_path = {
            pool.submit(
                calculate_corruption,
                path,
                chunk_size=args.chunk_size,
                gap=args.gap,
                full_scan=args.full_scan,
                audio_scan=args.audio_scan,
                threads=args.threads,
            ): path
            for path in args.paths
            if Path(path).suffix.lower() not in consts.SKIP_MEDIA_CHECK
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                corruption = future.result()
                print(strings.safe_percent(corruption), shlex.quote(path), sep="\t")
            except Exception as e:
                print(f"Error hashing {path}: {e}")
                if args.verbose >= consts.LOG_DEBUG:
                    raise
            else:
                if corruption_threshold_exceeded(args.delete_corrupt, corruption, processes.FFProbe(path).duration):
                    threshold_str = (
                        strings.safe_percent(args.delete_corrupt)
                        if 0 < args.delete_corrupt < 1
                        else (args.delete_corrupt + "s")
                    )
                    log.warning(
                        "Deleting %s corruption %.1f%% exceeded threshold %s", path, corruption * 100, threshold_str
                    )
                    file_utils.trash(path)
