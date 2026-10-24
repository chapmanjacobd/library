import argparse
import math
import re
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass

from library import usage
from library.utils import arggroups, argparse_utils, consts, nums, processes, shell_utils

FRAME_WIDTH = 160
FRAME_HEIGHT = 160
FRAME_CHANNELS = 3
FRAME_BYTES = FRAME_WIDTH * FRAME_HEIGHT * FRAME_CHANNELS
MIN_SAMPLES = 2
BLACK_MIN_DURATION = 0.8
BLACK_PIXEL_THRESHOLD = 0.1
DEFAULT_BLANK_DETECT_DURATION = 0.8
DEFAULT_STILL_IMAGE_RATIO = 0.95
MAX_FREEZE_SAMPLE_INTERVALS = 200
RESOLUTION_COMPONENTS = 2


@dataclass(frozen=True)
class Comparison:
    operator: str
    value: float
    tolerance: float = 0

    def matches(self, actual: float) -> bool:
        if self.operator == ">":
            return actual > self.value
        if self.operator == ">=":
            return actual >= self.value
        if self.operator == "<":
            return actual < self.value
        if self.operator == "<=":
            return actual <= self.value
        return math.isclose(actual, self.value, abs_tol=self.tolerance, rel_tol=0)


@dataclass(frozen=True)
class FreezeSpec:
    ratio: float | None = None
    duration: float | None = None


def parse_freeze_spec(value: str) -> FreezeSpec:
    value = value.strip().lower()
    if not value:
        raise ValueError("freeze-frame threshold must not be empty")

    if value.endswith("%"):
        ratio = float(value[:-1]) / 100
        if not 0 <= ratio <= 1:
            raise ValueError("freeze-frame percentage must be between 0% and 100%")
        return FreezeSpec(ratio=ratio)

    try:
        numeric_value = float(value)
    except ValueError:
        numeric_value = None
    if numeric_value is not None and 0 <= numeric_value <= 1:
        return FreezeSpec(ratio=numeric_value)

    if value.startswith("-"):
        raise ValueError("freeze-frame duration must not be negative")
    duration = nums.human_to_seconds(value)
    if duration <= 0:
        raise ValueError("freeze-frame duration must be greater than zero")
    return FreezeSpec(duration=duration)


def _parse_comparison(value: str, *, tolerance: float = 0) -> Comparison:
    value = value.strip()
    if not value:
        raise ValueError("comparison value must not be empty")

    operator = "="
    for prefix, comparison_operator in ((">=", ">="), ("<=", "<="), ("+", ">="), ("-", "<="), (">", ">"), ("<", "<")):
        if value.startswith(prefix):
            operator = comparison_operator
            value = value[len(prefix) :]
            break

    try:
        number = float(value)
    except ValueError as error:
        message = f"invalid comparison value: {value!r}"
        raise ValueError(message) from error
    if number < 0:
        raise ValueError("comparison value must not be negative")
    return Comparison(operator, number, tolerance)


def _parse_ratio(value: str) -> float:
    if ":" in value:
        numerator, denominator = value.split(":", 1)
    elif "/" in value:
        numerator, denominator = value.split("/", 1)
    else:
        return float(value)

    numerator = float(numerator)
    denominator = float(denominator)
    if numerator <= 0 or denominator <= 0:
        raise ValueError("aspect ratio values must be greater than zero")
    return numerator / denominator


def _parse_aspect_ratio(value: str) -> Comparison:
    value = value.strip()
    operator = ""
    for prefix in (">=", "<=", "+", "-", ">", "<"):
        if value.startswith(prefix):
            operator, value = prefix, value[len(prefix) :]
            break
    comparison = _parse_comparison(f"{operator}{_parse_ratio(value)}", tolerance=0.01)
    return comparison


def _parse_resolution(value: str) -> tuple[Comparison, Comparison]:
    parts = re.split(r"[xX]", value.strip())
    if len(parts) != RESOLUTION_COMPONENTS:
        raise ValueError("resolution must be WIDTHxHEIGHT")
    return _parse_comparison(parts[0]), _parse_comparison(parts[1])


def _looks_like_freeze_spec(value: str) -> bool:
    return bool(
        re.fullmatch(r"\d+(?:\.\d+)?%?", value)
        or re.fullmatch(
            r"\d+(?:\.\d+)?(?:s|sec|second|seconds|m|min|minute|minutes|h|hr|hour|hours|d|day|days|w|week|weeks|mo|mon|month|months|y|yr|year|years)",
            value.lower(),
        )
    )


def _normalize_freeze_args(argv: list[str]) -> list[str]:
    """Keep an optional freeze threshold from consuming the first input path."""
    aliases = {"--still-image", "--static-image", "--image", "--freeze-frame"}
    normalized = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument in aliases and index + 1 < len(argv):
            next_argument = argv[index + 1]
            if not next_argument.startswith("-") and not _looks_like_freeze_spec(next_argument):
                normalized.append(f"{argument}={DEFAULT_STILL_IMAGE_RATIO}")
                index += 1
                continue
        normalized.append(argument)
        index += 1
    return normalized


def _read_frame(stream):
    chunks = []
    bytes_remaining = FRAME_BYTES
    while bytes_remaining:
        chunk = stream.read(bytes_remaining)
        if not chunk:
            break
        chunks.append(chunk)
        bytes_remaining -= len(chunk)
    return b"".join(chunks)


def _iter_sampled_frames(path: str, duration: float, intervals: int):
    import numpy as np

    if intervals < 1:
        raise ValueError("intervals must be at least 1")

    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        path,
        "-an",
        "-vf",
        f"fps={intervals}/{duration:.9f},scale={FRAME_WIDTH}:{FRAME_HEIGHT},format=rgb24",
        "-frames:v",
        str(intervals + 1),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for _ in range(intervals + 1):
            raw_frame = _read_frame(process.stdout)
            if not raw_frame:
                break
            if len(raw_frame) != FRAME_BYTES:
                message = f"ffmpeg returned {len(raw_frame)} bytes, expected {FRAME_BYTES}"
                raise ValueError(message)
            yield np.frombuffer(raw_frame, dtype=np.uint8)

        stderr = process.stderr.read()
        returncode = process.wait(timeout=30)
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, command, stderr=stderr)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stdout.close()
        process.stderr.close()


def _get_probe(path: str):
    try:
        return processes.FFProbe(path)
    except (OSError, TimeoutError, subprocess.TimeoutExpired, processes.UnplayableFileError):
        return None


def _frame_mse(previous, frame) -> float:
    import numpy as np

    return float(np.mean((frame.astype(np.float32) - previous.astype(np.float32)) ** 2))


def _is_solid_color(frame) -> bool:
    import numpy as np

    pixels = frame.reshape(-1, FRAME_CHANNELS)
    return bool(np.all(pixels == pixels[0]))


def _freeze_sample_intervals(ratio: float, samples: int) -> int:
    if ratio <= 0:
        return samples
    intervals_for_boundary_precision = math.ceil(1 / max(1 - ratio, 1e-9))
    return min(MAX_FREEZE_SAMPLE_INTERVALS, max(samples, intervals_for_boundary_precision))


def has_freeze_frame(
    path: str,
    freeze: FreezeSpec,
    *,
    samples: int = 5,
    threshold: float = 1.0,
) -> bool:
    """Return whether a video contains a freeze frame lasting the requested time."""
    if samples < MIN_SAMPLES:
        raise ValueError("samples must be at least 2")
    if threshold < 0:
        raise ValueError("threshold must not be negative")

    probe = _get_probe(path)
    if probe is None or not probe.has_video or not probe.duration or probe.duration <= 0:
        return False

    if freeze.ratio is not None:
        return _has_freeze_ratio(path, probe.duration, freeze.ratio, samples, threshold)

    if freeze.duration is None:
        return False
    return _has_freeze_duration(path, freeze.duration, threshold)


def _has_freeze_ratio(path: str, video_duration: float, ratio: float, samples: int, threshold: float) -> bool:
    if ratio == 0:
        return True

    required_duration = video_duration * ratio
    intervals = _freeze_sample_intervals(ratio, samples)
    timestamps = [video_duration * index / intervals for index in range(intervals + 1)]
    previous = None
    previous_timestamp = None
    freeze_start = None
    try:
        with closing(_iter_sampled_frames(path, video_duration, intervals)) as frames:
            for timestamp in timestamps:
                try:
                    frame = next(frames)
                except StopIteration:
                    return False
                if previous is not None and _frame_mse(previous, frame) <= threshold:
                    if freeze_start is None:
                        freeze_start = previous_timestamp
                    if freeze_start is not None and timestamp - freeze_start >= required_duration:
                        return True
                else:
                    freeze_start = None
                previous = frame
                previous_timestamp = timestamp
    except (OSError, TimeoutError, StopIteration, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        return False
    return False


def _matches_full_frame_filters(  # noqa: PLR0911,PLR0912 - coordinates two streaming predicates
    path: str,
    freeze: FreezeSpec | None,
    *,
    blank: bool | None,
    blank_duration: float,
    samples: int,
    threshold: float,
) -> bool:
    del samples
    probe = _get_probe(path)
    if probe is None or not probe.has_video or not probe.duration or probe.duration <= 0:
        return False

    ratio = freeze.ratio if freeze is not None else None
    if ratio == 0 and blank is None:
        return True

    stream = _video_stream(probe)
    fps = _stream_fps(probe, stream) if stream is not None else None
    if fps is None or fps <= 0:
        return False
    intervals = max(1, math.ceil(probe.duration * fps))
    frame_duration = probe.duration / intervals
    freeze_frames = (
        math.ceil(probe.duration * ratio / frame_duration) + 1
        if ratio is not None and ratio > 0
        else 0
    )
    blank_frames = math.ceil(blank_duration / frame_duration) + 1
    freeze_run = 0
    blank_run = 0
    previous = None
    freeze_matches = ratio == 0 or ratio is None
    blank_matches = blank is not True
    try:
        with closing(_iter_sampled_frames(path, probe.duration, intervals)) as frames:
            for index in range(intervals + 1):
                try:
                    frame = next(frames)
                except StopIteration:
                    break

                if ratio is not None and ratio > 0:
                    if index and _frame_mse(previous, frame) <= threshold:
                        freeze_run += 1
                    else:
                        freeze_run = 1
                    if freeze_run >= freeze_frames:
                        freeze_matches = True

                if blank is not None:
                    if _is_solid_color(frame):
                        blank_run += 1
                    else:
                        blank_run = 0
                    if blank_run >= blank_frames:
                        if blank is False:
                            return False
                        blank_matches = True

                if freeze_matches and blank_matches and blank is not False:
                    return True
                previous = frame
    except (OSError, StopIteration, TimeoutError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        return False
    return freeze_matches and blank_matches


def _has_freeze_duration(path: str, duration: float, threshold: float) -> bool:
    noise_db = min(0, 20 * math.log10(max(math.sqrt(threshold), 1e-9) / 255))
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        path,
        "-vf",
        f"freezedetect=n={noise_db:.2f}dB:d={duration}",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, TimeoutError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False

    return any(
        float(match) >= duration
        for match in re.findall(r"freeze_duration:\s*([0-9]+(?:\.[0-9]+)?)", result.stderr or "")
    )


def has_blank_frame(path: str, *, samples: int = 5, min_duration: float = DEFAULT_BLANK_DETECT_DURATION) -> bool:
    """Return whether one RGB color spans at least ``min_duration``."""
    if samples < MIN_SAMPLES:
        raise ValueError("samples must be at least 2")
    if min_duration <= 0:
        raise ValueError("min_duration must be greater than zero")
    return _matches_full_frame_filters(
        path,
        None,
        blank=True,
        blank_duration=min_duration,
        samples=samples,
        threshold=0,
    )


def has_black_frame(path: str, *, min_duration: float = BLACK_MIN_DURATION) -> bool:
    """Return whether FFmpeg detects a black interval lasting at least ``min_duration``."""
    if min_duration <= 0:
        message = "min_duration must be greater than zero"
        raise ValueError(message)

    probe = _get_probe(path)
    if probe is None or not probe.has_video or not probe.duration or probe.duration <= 0:
        return False

    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        path,
        "-vf",
        f"blackdetect=d={min_duration:.9f}:pix_th={BLACK_PIXEL_THRESHOLD}",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, TimeoutError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return "black_duration:" in (result.stderr or "")


def is_still_image(path: str, *, samples: int = 5, threshold: float = 1.0) -> bool:
    """Return whether sampled video frames are visually identical."""
    if samples < MIN_SAMPLES:
        raise ValueError("samples must be at least 2")
    if threshold < 0:
        raise ValueError("threshold must not be negative")

    probe = _get_probe(path)
    if probe is None or not probe.has_video or not probe.duration or probe.duration <= 0:
        return False

    try:
        with closing(_iter_sampled_frames(path, probe.duration, samples + 1)) as frames:
            next(frames)
            previous = next(frames)
            for _ in range(samples - 1):
                frame = next(frames)
                if _frame_mse(previous, frame) > threshold:
                    return False
                previous = frame
    except (OSError, TimeoutError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        return False

    return True


def _video_stream(probe):
    return next(iter(getattr(probe, "video_streams", [])), None)


def _stream_fps(probe, stream) -> float | None:
    if getattr(probe, "fps", None) is not None:
        return probe.fps
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        if value and "/" in value:
            numerator, denominator = value.split("/", 1)
            if float(denominator):
                return float(numerator) / float(denominator)
    return None


def _stream_aspect_ratio(stream) -> float | None:
    display_aspect_ratio = stream.get("display_aspect_ratio")
    if display_aspect_ratio and display_aspect_ratio != "0:1":
        try:
            return _parse_ratio(display_aspect_ratio)
        except (ValueError, ZeroDivisionError):
            pass

    width = stream.get("width")
    height = stream.get("height")
    if not width or not height:
        return None

    aspect_ratio = float(width) / float(height)
    sample_aspect_ratio = stream.get("sample_aspect_ratio")
    if sample_aspect_ratio and sample_aspect_ratio != "0:1":
        try:
            aspect_ratio *= _parse_ratio(sample_aspect_ratio)
        except (ValueError, ZeroDivisionError):
            pass
    return aspect_ratio


def matches_metadata_filters(path: str, args) -> bool:
    needs_metadata = any(
        value is not None
        for value in (args.fps, args.resolution, args.width, args.height, args.aspect_ratio)
    )
    if not needs_metadata:
        return True

    probe = _get_probe(path)
    if probe is None:
        return False
    stream = _video_stream(probe)
    if stream is None:
        return False

    matches = True
    if args.fps is not None:
        fps = _stream_fps(probe, stream)
        matches = fps is not None and args.fps.matches(fps)

    resolution = args.resolution or ()
    width_filter = args.width or (resolution[0] if resolution else None)
    height_filter = args.height or (resolution[1] if resolution else None)
    if width_filter is not None:
        matches = matches and width_filter.matches(float(stream.get("width") or 0))
    if height_filter is not None:
        matches = matches and height_filter.matches(float(stream.get("height") or 0))

    if args.aspect_ratio is not None:
        aspect_ratio = _stream_aspect_ratio(stream)
        matches = matches and aspect_ratio is not None and args.aspect_ratio.matches(aspect_ratio)
    return matches


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.video_detect)
    parser.add_argument(
        "--still-image",
        "--static-image",
        "--image",
        "--freeze-frame",
        dest="still_image",
        nargs="?",
        const=str(DEFAULT_STILL_IMAGE_RATIO),
        metavar="PERCENT|DURATION",
        help="Find a freeze frame lasting this fraction or duration (default: 95%%)",
    )
    black_mode = parser.add_mutually_exclusive_group()
    black_mode.add_argument(
        "--black",
        dest="black",
        action="store_true",
        help="Find videos containing at least 800ms of black-ish video (FFmpeg blackdetect)",
    )
    black_mode.add_argument(
        "--no-black",
        dest="black",
        action="store_false",
        help="Find videos without at least 800ms of black-ish video",
    )
    parser.add_argument(
        "--black-detect-duration",
        default="800ms",
        metavar="DURATION",
        help="Minimum blackdetect interval (default: 800ms)",
    )
    blank_mode = parser.add_mutually_exclusive_group()
    blank_mode.add_argument(
        "--blank",
        dest="blank",
        action="store_true",
        help="Find videos containing one exact color for the configured duration",
    )
    blank_mode.add_argument(
        "--no-blank",
        dest="blank",
        action="store_false",
        help="Find videos without one exact color lasting the configured duration",
    )
    parser.add_argument(
        "--blank-detect-duration",
        default="800ms",
        metavar="DURATION",
        help="Minimum exact-color interval (default: 800ms)",
    )
    parser.set_defaults(black=None, blank=None)
    parser.add_argument("--fps", metavar="RANGE", help="Match frame rate; -N means <=N and +N means >=N")
    parser.add_argument(
        "--resolution",
        metavar="WIDTHxHEIGHT",
        help="Match dimensions, with optional +/- comparisons per component",
    )
    parser.add_argument("--width", metavar="RANGE", help="Match video width; -N means <=N and +N means >=N")
    parser.add_argument("--height", metavar="RANGE", help="Match video height; -N means <=N and +N means >=N")
    parser.add_argument("--aspect-ratio", metavar="RATIO", help="Match display aspect ratio, such as 16:9 or +1.5")
    parser.add_argument("--samples", type=int, default=5, help="Number of frames to compare (default: 5)")
    parser.add_argument("--threshold", type=float, default=1.0, help="Maximum consecutive-frame MSE (default: 1.0)")
    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args(_normalize_freeze_args(sys.argv[1:]))
    try:
        if args.still_image is not None:
            args.still_image = parse_freeze_spec(args.still_image)
        for name in ("black_detect_duration", "blank_detect_duration"):
            duration = nums.human_to_seconds(getattr(args, name))
            if duration <= 0:
                message = f"--{name.replace('_', '-')} must be greater than zero"
                raise ValueError(message)
            setattr(args, name, duration)
        if args.fps is not None:
            args.fps = _parse_comparison(args.fps)
        if args.resolution is not None:
            args.resolution = _parse_resolution(args.resolution)
        if args.width is not None:
            args.width = _parse_comparison(args.width)
        if args.height is not None:
            args.height = _parse_comparison(args.height)
        if args.aspect_ratio is not None:
            args.aspect_ratio = _parse_aspect_ratio(args.aspect_ratio)
    except ValueError as error:
        parser.error(str(error))

    if not any(
        value is not None
        for value in (
            args.still_image,
            args.black,
            args.blank,
            args.fps,
            args.resolution,
            args.width,
            args.height,
            args.aspect_ratio,
        )
    ):
        parser.error("select at least one detection mode")
    arggroups.args_post(args, parser)
    return args


def detect() -> None:  # noqa: PLR0912 - coordinates independent detector predicates
    args = parse_args()
    if args.samples < MIN_SAMPLES:
        raise ValueError("--samples must be at least 2")
    if args.threshold < 0:
        raise ValueError("--threshold must not be negative")

    for media in shell_utils.gen_d(args, consts.VIDEO_EXTENSIONS):
        path = media["path"]
        if args.still_image is not None and args.still_image.duration is not None:
            if not has_freeze_frame(
                path,
                args.still_image,
                samples=args.samples,
                threshold=args.threshold,
            ):
                continue
            if args.blank is not None and has_blank_frame(
                path,
                samples=args.samples,
                min_duration=args.blank_detect_duration,
            ) != args.blank:
                continue
        elif args.still_image is not None and args.blank is not None:
            if not _matches_full_frame_filters(
                path,
                args.still_image,
                blank=args.blank,
                blank_duration=args.blank_detect_duration,
                samples=args.samples,
                threshold=args.threshold,
            ):
                continue
        elif args.still_image is not None:
            if not has_freeze_frame(
                path,
                args.still_image,
                samples=args.samples,
                threshold=args.threshold,
            ):
                continue
        elif args.blank is not None and has_blank_frame(
            path,
            samples=args.samples,
            min_duration=args.blank_detect_duration,
        ) != args.blank:
            continue
        if args.black is not None and has_black_frame(path, min_duration=args.black_detect_duration) != args.black:
            continue
        if not matches_metadata_filters(path, args):
            continue
        print(path)


is_static_image = is_still_image
detect_static_image = detect
