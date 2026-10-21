import argparse
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from itertools import pairwise

from library import usage
from library.utils import arggroups, argparse_utils, consts, nums, processes, shell_utils

FRAME_WIDTH = 160
FRAME_HEIGHT = 160
MIN_SAMPLES = 2
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


def _sample_frame(path: str, timestamp: float):
    import numpy as np

    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(timestamp),
            "-i",
            path,
            "-frames:v",
            "1",
            "-vf",
            f"scale={FRAME_WIDTH}:{FRAME_HEIGHT}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

    frame = np.frombuffer(result.stdout, dtype=np.uint8)
    expected_size = FRAME_WIDTH * FRAME_HEIGHT
    if frame.size != expected_size:
        message = f"ffmpeg returned {frame.size} pixels, expected {expected_size}"
        raise ValueError(message)
    return frame


def _get_probe(path: str):
    try:
        return processes.FFProbe(path)
    except (OSError, TimeoutError, subprocess.TimeoutExpired, processes.UnplayableFileError):
        return None


def _sample_timestamps(duration: float, samples: int) -> list[float]:
    return [duration * index / (samples + 1) for index in range(1, samples + 1)]


def _frame_mse(previous, frame) -> float:
    import numpy as np

    return float(np.mean((frame.astype(np.float32) - previous.astype(np.float32)) ** 2))


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
        for timestamp in timestamps:
            frame = _sample_frame(path, timestamp)
            if previous is not None and _frame_mse(previous, frame) <= threshold:
                if freeze_start is None:
                    freeze_start = previous_timestamp
                if timestamp - freeze_start >= required_duration:
                    return True
            else:
                freeze_start = None
            previous = frame
            previous_timestamp = timestamp
    except (OSError, TimeoutError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        return False
    return False


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


def has_blank_frame(path: str, *, samples: int = 5) -> bool:
    """Return whether sampled frames contain a single luma value."""
    if samples < MIN_SAMPLES:
        raise ValueError("samples must be at least 2")

    probe = _get_probe(path)
    if probe is None or not probe.has_video or not probe.duration or probe.duration <= 0:
        return False

    import numpy as np

    try:
        for timestamp in _sample_timestamps(probe.duration, samples):
            frame = _sample_frame(path, timestamp)
            if np.ptp(frame) <= 1:
                return True
    except (OSError, TimeoutError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        return False
    return False


def is_still_image(path: str, *, samples: int = 5, threshold: float = 1.0) -> bool:
    """Return whether sampled video frames are visually identical."""
    if samples < MIN_SAMPLES:
        raise ValueError("samples must be at least 2")
    if threshold < 0:
        raise ValueError("threshold must not be negative")

    probe = _get_probe(path)
    if probe is None or not probe.has_video or not probe.duration or probe.duration <= 0:
        return False

    timestamps = _sample_timestamps(probe.duration, samples)
    try:
        frames = [_sample_frame(path, timestamp) for timestamp in timestamps]
    except (OSError, TimeoutError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        return False

    return all(_frame_mse(previous, frame) <= threshold for previous, frame in pairwise(frames))


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
    blank_mode = parser.add_mutually_exclusive_group()
    blank_mode.add_argument(
        "--black",
        "--blank",
        dest="black",
        action="store_true",
        help="Find videos containing a sampled single-color frame",
    )
    blank_mode.add_argument(
        "--no-black",
        "--no-blank",
        dest="black",
        action="store_false",
        help="Find videos without sampled single-color frames",
    )
    parser.set_defaults(black=None)
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
        for value in (args.still_image, args.black, args.fps, args.resolution, args.width, args.height, args.aspect_ratio)
    ):
        parser.error("select at least one detection mode")
    arggroups.args_post(args, parser)
    return args


def detect() -> None:
    args = parse_args()
    if args.samples < MIN_SAMPLES:
        raise ValueError("--samples must be at least 2")
    if args.threshold < 0:
        raise ValueError("--threshold must not be negative")

    for media in shell_utils.gen_d(args, consts.VIDEO_EXTENSIONS):
        path = media["path"]
        if args.still_image is not None and not has_freeze_frame(
            path,
            args.still_image,
            samples=args.samples,
            threshold=args.threshold,
        ):
            continue
        if args.black is not None and has_blank_frame(path, samples=args.samples) != args.black:
            continue
        if not matches_metadata_filters(path, args):
            continue
        print(path)


is_static_image = is_still_image
detect_static_image = detect
