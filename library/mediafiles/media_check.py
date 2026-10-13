import fractions, os, shlex, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from shutil import which

from library.utils import arggroups, argparse_utils, consts, nums, path_utils, printing, processes, shell_utils, strings
from library.utils.log_utils import log
from library.utils.shell_utils import gen_paths

USAGE = {
    'media_check': """library file check [--chunk-size SECONDS] [--gap SECONDS OR 0.0-1.0*DURATION] [--delete-corrupt >0-100] [--full-scan] [--audio-scan] PATH ...

    Defaults to decode 0.5 second per 10% of each file

        library file check ./video.mp4

    Decode all the frames of each file to evaluate how corrupt it is
    (scantime is very slow; about 150 seconds for an hour-long file)

        library file check --full-scan ./video.mp4

    Decode all the packets of each file to evaluate how corrupt it is
    (scantime is about one second of each file but only accurate for formats where 1 packet == 1 frame)

        library file check --full-scan --gap 0 ./video.mp4

    Decode all audio of each file to evaluate how corrupt it is
    (scantime is about four seconds per file)

        library file check --full-scan --audio ./video.mp4

    Decode at least one frame at the start and end of each file to evaluate how corrupt it is
    (scantime is about one second per file)

        library file check --chunk-size 5% --gap 99.9% ./video.mp4

    Decode 3s every 5% of a file to evaluate how corrupt it is
    (scantime is about three seconds per file)

        library file check --chunk-size 3 --gap 5% ./video.mp4

    Delete the file if 20 percent or more of checks fail

        library file check --delete-corrupt 20% ./video.mp4

    To scan a large folder use `fsadd`. I recommend something like this two-stage approach

        library database add filesystem --delete-unplayable --check-corrupt --chunk-size 5% tmp.db ./video/ ./folders/
        library file check (library database filesystem list tmp.db -w 'corruption>15' -pf) --full-scan --delete-corrupt 25%

    This runs in one command via `--full-scan-if-corrupt`:

        library database add filesystem --delete-unplayable --check-corrupt --chunk-size 5% tmp.db ./video/ ./folders/ --full-scan-if-corrupt 15% --delete-corrupt 25%

    Corruption stats

        library database filesystem list tmp.db -w 'corruption>15' -pa
        path         count  duration             avg_duration         size    avg_size
        ---------  -------  -------------------  --------------  ---------  ----------
        Aggregate      907  15 days and 9 hours  24 minutes      130.6 GiB   147.4 MiB

    Corruption graph

        sqlite --raw-lines tmp.db 'select corruption from media' | lowcharts hist --min 10 --intervals 10

        Samples = 931; Min = 10.0; Max = 100.0
        Average = 39.1; Variance = 1053.103; STD = 32.452
        each ∎ represents a count of 6
        [ 10.0 ..  19.0] [561] ∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎
        [ 19.0 ..  28.0] [ 69] ∎∎∎∎∎∎∎∎∎∎∎
        [ 28.0 ..  37.0] [ 33] ∎∎∎∎∎
        [ 37.0 ..  46.0] [ 18] ∎∎∎
        [ 46.0 ..  55.0] [ 14] ∎∎
        [ 55.0 ..  64.0] [ 12] ∎∎
        [ 64.0 ..  73.0] [ 15] ∎∎
        [ 73.0 ..  82.0] [ 18] ∎∎∎
        [ 82.0 ..  91.0] [ 50] ∎∎∎∎∎∎∎∎
        [ 91.0 .. 100.0] [141] ∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎
""",
}


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=USAGE['media_check'])
    arggroups.capability_delete(parser)
    arggroups.media_check(parser)
    arggroups.debug(parser)
    parser.set_defaults(same_file_threads=2, threads=4)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    return args


def decode_quick_scan(path, scans, scan_duration=3, audio_scan=False):
    assert which("ffmpeg")

    def decode(scan):
        opts = []
        if audio_scan:
            opts += [
                "-map",
                "0:a",
                "-c:a",
                "copy",
                "-map_metadata",
                "-1",
            ]

        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-xerror",
            "-v",
            "16",
            "-err_detect",
            "buffer+crccheck+explode",
            "-ss",
            f"{scan:.2f}",
            "-i",
            path,
            "-t",
            str(scan_duration),
            *opts,
            "-f",
            "null",
            os.devnull,
        ]

        proc = processes.cmd(*cmd, limit_ram=True, nice=5, journald=False)
        # I wonder if something like this would be faster: -map 0:v:0 -filter:v "select=eq(pict_type\,I)" -frames:v 1
        if proc.stderr != "":
            raise RuntimeError

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(decode, scan) for scan in scans]

    fail_count = 0
    for future in futures:
        try:
            future.result()
        except (RuntimeError, subprocess.CalledProcessError):
            fail_count += 1

    return fail_count / len(scans)


def decode_full_scan(path, audio_scan=False, frames="frames", threads=None):
    ffprobe = processes.FFProbe(path)
    metadata_duration = ffprobe.duration or 0

    if audio_scan or not ffprobe.has_video:
        try:
            with tempfile.NamedTemporaryFile(suffix=".mkv") as temp_output:
                processes.cmd(
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-nostats",
                    "-v",
                    "16",
                    "-i",
                    path,
                    "-map",
                    "0:a",
                    "-c:a",
                    "copy",
                    "-map_metadata",
                    "-1",
                    "-y",
                    temp_output.name,
                    nice=3,
                    journald=False,
                )
                actual_duration = processes.FFProbe(temp_output.name).duration or 0
        except subprocess.CalledProcessError:
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
            str(threads or 1),
            "-v",
            "0",
            path,
        ]

        r_frames = processes.cmd(*ffprobe_cmd, nice=3, journald=False)
        data = strings.safe_json_loads(r_frames.stdout)["streams"][0]

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
            f"Metadata {printing.seconds_to_hhmmss(metadata_duration).strip()} does not match actual duration {printing.seconds_to_hhmmss(actual_duration).strip()} (diff {difference:.2f}s): {path}",
        )

    return corruption


def corruption_threshold_exceeded(threshold: bool | float, corruption, duration):
    if threshold:
        if threshold is True:
            threshold = 0.069

        if 0 < threshold < 1:
            if corruption >= threshold:
                return True
        elif ((duration or 100) * corruption) >= threshold:
            return True
    return False


def calculate_corruption(
    path,
    chunk_size=1,
    gap=0.1,
    full_scan=False,
    full_scan_if_corrupt: bool | float = False,
    audio_scan=False,
    threads=1,
):
    if full_scan:
        if gap == 0:
            corruption = decode_full_scan(path, audio_scan=audio_scan, frames="packets", threads=threads)
        else:
            corruption = decode_full_scan(path, audio_scan=audio_scan, threads=threads)
    else:
        duration = processes.FFProbe(path).duration
        duration = nums.safe_int(duration)
        if duration in [None, 0]:
            return 0.5
        corruption = decode_quick_scan(
            path,
            scans=nums.calculate_segments(duration, chunk_size, gap),
            scan_duration=chunk_size,
            audio_scan=audio_scan,
        )
        if corruption_threshold_exceeded(full_scan_if_corrupt, corruption, duration):
            corruption = decode_full_scan(path, audio_scan=audio_scan, threads=threads)
    return corruption


def media_check() -> None:
    args = parse_args()
    paths = list(gen_paths(args))

    with ThreadPoolExecutor(max_workers=1 if args.verbose >= consts.LOG_DEBUG else args.threads) as pool:
        future_to_path = {
            pool.submit(
                calculate_corruption,
                path,
                chunk_size=args.chunk_size,
                gap=args.gap,
                full_scan=args.full_scan,
                full_scan_if_corrupt=args.full_scan_if_corrupt,
                audio_scan=args.audio_scan,
                threads=args.same_file_threads,
            ): path
            for path in paths
            if path_utils.ext(path) not in consts.SKIP_MEDIA_CHECK
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                corruption = future.result()
                print(strings.percent(corruption), shlex.quote(path), sep="\t")
            except Exception as excinfo:
                print(f"Error checking {path}: {excinfo}")
                if args.verbose >= consts.LOG_DEBUG:
                    raise
            else:
                duration = processes.FFProbe(path).duration

                if corruption_threshold_exceeded(args.delete_corrupt, corruption, duration):
                    threshold_str = (
                        strings.percent(args.delete_corrupt)
                        if 0 < args.delete_corrupt < 1
                        else f"{args.delete_corrupt}s"
                    )
                    log.warning(
                        "Deleting %s corruption %.1f%% exceeded threshold %s", path, corruption * 100, threshold_str
                    )
                    shell_utils.trash(args, path)
