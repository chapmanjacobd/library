import fractions, os, shlex, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from shutil import which

from xklb import usage
from xklb.utils import arggroups, argparse_utils, consts, file_utils, nums, path_utils, printing, processes, strings
from xklb.utils.arg_utils import gen_paths
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.media_check)
    arggroups.capability_delete(parser)
    arggroups.media_check(parser)
    arggroups.debug(parser)
    parser.set_defaults(same_file_threads=2, threads=4)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.media_check_post(args)
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

        cmd = []
        if which("systemd-run"):
            cmd += ["systemd-run"]
            if not "SUDO_UID" in os.environ:
                cmd += ["--user"]
            cmd += [
                "-p",
                "MemoryMax=4G",
                "-p",
                "MemorySwapMax=1G",
                "--pty",
                "--pipe",
                "--same-dir",
                "--wait",
                "--collect",
                "--service-type=exec",
                "--quiet",
                "--",
            ]
        cmd += [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
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
            *opts,
            "-f",
            "null",
            os.devnull,
        ]

        proc = processes.cmd(*cmd)
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

        r_frames = processes.cmd(*ffprobe_cmd)
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
            threshold = 0.15

        if 1 > threshold > 0:
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
        duration = nums.safe_int(processes.FFProbe(path).duration)
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
                    file_utils.trash(args, path)
