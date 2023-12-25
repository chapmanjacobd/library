import argparse, fractions, json, os, shlex, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from xklb import usage
from xklb.utils import consts, file_utils, nums, objects, printing, processes
from xklb.utils.log_utils import log


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
            str(scan),
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
        nb_frames = int(data[f"nb_read_{frames}"])
        metadata_duration = ffprobe.duration or 0
        actual_duration = nb_frames * r_frame_rate.denominator / r_frame_rate.numerator

    difference = abs(actual_duration - metadata_duration)
    corruption = difference / metadata_duration

    if difference > 0.1:
        log.warning(
            f"Metadata {printing.seconds_to_hhmmss(metadata_duration).strip()} does not match actual duration {printing.seconds_to_hhmmss(actual_duration).strip()} (diff {difference:.2f}s) {path}",
        )

    return corruption


def calculate_corruption(path, chunk_size=1, gap=0.1, full_scan=False, audio_scan=False, threads=5):
    if full_scan:
        if gap == 0:
            corruption = decode_full_scan(path, audio_scan=audio_scan, frames="packets", threads=threads)
        else:
            corruption = decode_full_scan(path, audio_scan=audio_scan, threads=threads)
    else:
        duration = nums.safe_int(processes.FFProbe(path).duration)
        corruption = decode_quick_scan(path, nums.calculate_segments(duration, chunk_size, gap), chunk_size)
    return corruption


def media_check() -> None:
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
        type=float,
        default=0.1,
        help="Width between chunks to skip (default 0.10 (10%%)). Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument(
        "--delete-corrupt",
        type=float,
        help="delete media that is more corrupt than this threshold",
    )
    parser.add_argument("--full-scan", "--full", action="store_true")
    parser.add_argument("--audio-scan", "--audio", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    log.info(objects.dict_filter_bool(args.__dict__))

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
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                corruption = future.result()
                print(f"{corruption:.2%}", shlex.quote(path), sep="\t")
            except Exception as e:
                print(f"Error hashing {path}: {e}")
                if args.verbose >= consts.LOG_DEBUG:
                    raise
            else:
                if args.delete_corrupt and corruption > (args.delete_corrupt / 100):
                    file_utils.trash(path)
