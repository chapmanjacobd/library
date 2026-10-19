import argparse
import math
import random
import shlex
import tempfile
from pathlib import Path

from natsort import natsorted

from library import usage
from library.utils import arggroups, argparse_utils, consts, devices, processes, shell_utils


IMAGE_EXTENSIONS = consts.IMAGE_EXTENSIONS | consts.PIL_EXTENSIONS


def _parser(usage_text: str) -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(usage=usage_text)
    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-dest")
    arggroups.debug(parser)
    return parser


def _parse_paths(args, extensions, required=True) -> list[Path]:
    if args.paths is None and not required:
        return []
    paths = [Path(path).expanduser() for path in shell_utils.gen_paths(args, extensions)]
    if required and not paths:
        processes.exit_error("No input paths passed in")
    for path in paths:
        if "://" in str(path):
            message = f"Video creation requires local paths: {path}"
            raise ValueError(message)
    return natsorted(paths)


def _destination(args, source: Path, default_name: str) -> Path:
    if getattr(args, "output_dir", None):
        return Path(args.output_dir).expanduser() / default_name
    if getattr(args, "output", None):
        return Path(args.output).expanduser()
    return source.with_name(default_name)


def _prepare_destination(args, destination: Path) -> str | None:
    if destination.exists() and args.file_over_file[-1] == arggroups.FileOverFile.SKIP:
        return None
    if not args.simulate:
        destination.parent.mkdir(parents=True, exist_ok=True)
    return devices.clobber_new_file(args, str(destination))


def _run(command: list[str], args) -> None:
    if args.simulate:
        print(shlex.join(command))
    else:
        processes.cmd(*command, limit_ram=True, nice=5, journald=False)


def _verify_output(destination: str, args) -> None:
    if not args.simulate and not Path(destination).exists():
        message = f"FFmpeg did not produce {destination}"
        raise RuntimeError(message)


def _fit_filter(args) -> str:
    if args.fit == "crop":
        return (
            f"scale={args.width}:{args.height}:force_original_aspect_ratio=increase,"
            f"crop={args.width}:{args.height}"
        )
    if args.fit == "stretch":
        return f"scale={args.width}:{args.height}"
    return (
        f"scale={args.width}:{args.height}:force_original_aspect_ratio=decrease,"
        f"pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )


def _video_filter(args) -> str:
    return f"{_fit_filter(args)},format=yuv420p"


def _image_inputs(paths: list[Path], args) -> list[str]:
    command = []
    for path in paths:
        command += ["-loop", "1"]
        if args.motion != "none":
            command += ["-framerate", str(args.fps)]
        command += ["-t", str(args.picture_time), "-i", str(path)]
    return command


def _audio_input(args) -> list[str]:
    if not args.audio:
        return []
    command = []
    for path in args.audio:
        if args.loop_audio:
            command += ["-stream_loop", "-1"]
        command += ["-i", str(path)]
    return command


def _audio_filter(args, output_duration: float) -> str | None:
    filters = []
    if args.audio_volume != 1:
        filters.append(f"volume={args.audio_volume:g}")
    if args.audio_fade_in:
        filters.append(f"afade=t=in:st=0:d={args.audio_fade_in:g}")
    if args.audio_fade_out:
        fade_duration = min(args.audio_fade_out, output_duration)
        fade_start = max(0, output_duration - fade_duration)
        filters.append(f"afade=t=out:st={fade_start:g}:d={fade_duration:g}")
    return ",".join(filters) or None


def _audio_concat_filter(args, first_audio_index: int) -> tuple[str | None, str | None]:
    if not args.audio:
        return None, None
    if len(args.audio) == 1:
        return None, f"{first_audio_index}:a:0"

    inputs = "".join(
        f"[{index}:a:0]" for index in range(first_audio_index, first_audio_index + len(args.audio))
    )
    return f"{inputs}concat=n={len(args.audio)}:v=0:a=1[audio]", "[audio]"


def _audio_output_options(args, audio_map: str | None, output_duration: float) -> list[str]:
    if not args.audio:
        return []
    assert audio_map is not None
    command = ["-map", audio_map, "-c:a", "aac"]
    audio_filter = _audio_filter(args, output_duration)
    if audio_filter:
        command += ["-af", audio_filter]
    command += ["-shortest"]
    return command


def _concat_image_command(list_path: str, destination: str, args, output_duration: float) -> list[str]:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_path,
    ]
    command += _audio_input(args)
    audio_filter, audio_map = _audio_concat_filter(args, 1)
    if audio_filter:
        command += [
            "-filter_complex",
            f"[0:v:0]{_video_filter(args)}[video];{audio_filter}",
            "-map",
            "[video]",
        ]
    else:
        command += ["-vf", _video_filter(args)]
    command += [
        "-r",
        str(args.fps),
        "-c:v",
        "libx264",
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-t",
        f"{output_duration + (1 / args.fps):g}",
    ]
    if args.audio and not audio_filter:
        command += ["-map", "0:v:0"]
    command += _audio_output_options(args, audio_map, output_duration)
    command.append(destination)
    return command


def _motion_filter(index: int, args) -> str:
    frames = max(args.picture_time * args.fps, 1)
    zoom_step = (args.motion_zoom - 1) / frames
    return (
        f"[{index}:v]{_fit_filter(args)},"
        f"zoompan=z='min(zoom+{zoom_step:g},{args.motion_zoom:g})':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={args.width}x{args.height}:fps={args.fps},format=yuv420p[v{index}]"
    )


def _image_filter(index: int, args) -> str:
    if args.motion == "ken-burns":
        return _motion_filter(index, args)
    return f"[{index}:v]{_video_filter(args)}[v{index}]"


def _crossfade_image_command(paths: list[Path], destination: str, args, output_duration: float) -> list[str]:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-y"]
    command += _image_inputs(paths, args)
    command += _audio_input(args)
    audio_filter, audio_map = _audio_concat_filter(args, len(paths))

    filters = [_image_filter(index, args) for index in range(len(paths))]
    previous = "v0"
    offset = args.picture_time - args.crossfade_time
    for index in range(1, len(paths)):
        output = f"xf{index}"
        filters.append(
            f"[{previous}][v{index}]xfade=transition=fade:duration={args.crossfade_time:g}:offset={offset:g}[{output}]"
        )
        previous = output
        offset += args.picture_time - args.crossfade_time
    if audio_filter:
        filters.append(audio_filter)

    command += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        f"[{previous}]",
        "-r",
        str(args.fps),
        "-c:v",
        "libx264",
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-t",
        f"{output_duration:g}",
    ]
    command += _audio_output_options(args, audio_map, output_duration)
    command.append(destination)
    return command


def _motion_image_command(paths: list[Path], destination: str, args, output_duration: float) -> list[str]:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-y"]
    command += _image_inputs(paths, args)
    command += _audio_input(args)
    audio_filter, audio_map = _audio_concat_filter(args, len(paths))

    filters = [_motion_filter(index, args) for index in range(len(paths))]
    inputs = "".join(f"[v{index}]" for index in range(len(paths)))
    filters.append(f"{inputs}concat=n={len(paths)}:v=1:a=0[v]")
    if audio_filter:
        filters.append(audio_filter)
    command += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[v]",
        "-r",
        str(args.fps),
        "-c:v",
        "libx264",
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-t",
        f"{output_duration:g}",
    ]
    command += _audio_output_options(args, audio_map, output_duration)
    command.append(destination)
    return command


def _black_audio_command(destination: str, args, output_duration: float) -> list[str]:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={args.width}x{args.height}:r={args.fps}",
    ]
    command += _audio_input(args)
    audio_filter, audio_map = _audio_concat_filter(args, 1)
    if audio_filter:
        command += ["-filter_complex", audio_filter]
    command += [
        "-map",
        "0:v:0",
        "-c:v",
        "libx264",
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-t",
        f"{output_duration:g}",
    ]
    command += _audio_output_options(args, audio_map, output_duration)
    command.append(destination)
    return command


def _slideshow_duration(image_count: int, args) -> float:
    return image_count * args.picture_time - max(image_count - 1, 0) * args.crossfade_time


def parse_images_args() -> argparse.Namespace:
    parser = _parser(usage.images_to_video)
    parser.add_argument(
        "--picture-time",
        "--duration",
        type=float,
        default=7,
        help="Seconds to show each image",
    )
    parser.add_argument(
        "--crossfade-time",
        type=float,
        default=0,
        help="Seconds of fade between images (default: no fade)",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        action="append",
        help="Audio track or directory to add; repeat to concatenate tracks",
    )
    audio_mode = parser.add_mutually_exclusive_group()
    audio_mode.add_argument(
        "--audio-duration",
        "--fit-audio",
        action="store_true",
        help="Set image timing to fit one pass of the images to the audio duration",
    )
    audio_mode.add_argument(
        "--loop-images",
        "--repeat-images",
        action="store_true",
        help="Repeat the image sequence until the audio track ends",
    )
    audio_mode.add_argument(
        "--hold-last-image",
        "--hold-last",
        action="store_true",
        help="Hold the final image until the audio track ends",
    )
    audio_mode.add_argument(
        "--loop-audio",
        action="store_true",
        help="Repeat the audio track until the slideshow ends",
    )
    parser.add_argument("--audio-fade-in", type=float, default=0, help="Fade audio in over this many seconds")
    parser.add_argument("--audio-fade-out", type=float, default=0, help="Fade audio out over this many seconds")
    parser.add_argument("--audio-volume", type=float, default=1, help="Audio volume multiplier")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle images before creating the slideshow")
    parser.add_argument("--seed", type=int, help="Random seed used with --shuffle")
    parser.add_argument("--fit", choices=("contain", "crop", "stretch"), default="contain")
    parser.add_argument(
        "--motion",
        choices=("none", "ken-burns"),
        default="none",
        help="Motion effect to apply to each image",
    )
    parser.add_argument("--motion-zoom", type=float, default=1.15, help="Maximum zoom for --motion ken-burns")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--output", "-o")
    parser.add_argument("--output-dir")
    arggroups.paths_or_stdin(parser, required=False)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    return args


def _validate_images_args(args) -> None:
    if args.picture_time <= 0:
        raise ValueError("--picture-time must be greater than zero")
    if args.crossfade_time < 0 or args.crossfade_time >= args.picture_time:
        raise ValueError("--crossfade-time must be at least zero and less than --picture-time")
    if args.width <= 0 or args.height <= 0 or args.fps <= 0:
        raise ValueError("--width, --height, and --fps must be greater than zero")
    if args.audio_fade_in < 0 or args.audio_fade_out < 0:
        raise ValueError("--audio-fade-in and --audio-fade-out must not be negative")
    if args.audio_volume < 0:
        raise ValueError("--audio-volume must not be negative")
    if args.motion_zoom < 1:
        raise ValueError("--motion-zoom must be at least one")
    if args.seed is not None and not args.shuffle:
        raise ValueError("--seed requires --shuffle")


def _parse_audio_paths(args) -> list[Path]:
    if not args.audio:
        return []

    paths = []
    for path in args.audio:
        path = Path(path).expanduser()
        if path.is_dir():
            paths.extend(Path(p) for p in shell_utils.rglob(path, consts.AUDIO_ONLY_EXTENSIONS, quiet=True)[0])
        else:
            paths.append(path)

    if not paths:
        raise ValueError("No audio files found")
    args.audio = natsorted(paths)
    return args.audio


def _audio_duration(args) -> float | None:
    audio_mode = args.audio_duration or args.loop_images or args.hold_last_image or args.loop_audio
    audio_filter = args.audio_fade_in or args.audio_fade_out or args.audio_volume != 1
    if not args.audio and (audio_mode or audio_filter):
        raise ValueError("--audio is required for audio modes and audio filters")
    if args.audio:
        durations = []
        for path in args.audio:
            if not path.is_file():
                message = f"Audio file not found: {path}"
                raise FileNotFoundError(message)
            probe = processes.FFProbe(str(path))
            if not probe.audio_streams:
                message = f"No audio stream found: {path}"
                raise ValueError(message)
            duration = probe.duration
            if not duration or duration <= 0:
                message = f"Could not determine audio duration: {path}"
                raise ValueError(message)
            durations.append(duration)
        return sum(durations)
    return None


def _fit_images_to_audio(paths: list[Path], args, audio_duration: float) -> list[Path]:
    if args.audio_duration:
        args.picture_time = (audio_duration + (len(paths) - 1) * args.crossfade_time) / len(paths)
        if args.crossfade_time >= args.picture_time:
            raise ValueError("--crossfade-time must be less than the calculated picture time")
        return paths

    image_duration = args.picture_time - args.crossfade_time
    if image_duration <= 0:
        raise ValueError("--picture-time must be greater than --crossfade-time")
    image_count = math.ceil(max(audio_duration - args.crossfade_time, 0) / image_duration)
    image_count = max(len(paths), image_count)
    if args.loop_images:
        image_count = math.ceil(image_count / len(paths)) * len(paths)
        return [path for _ in range(image_count // len(paths)) for path in paths]
    return [*paths, *([paths[-1]] * (image_count - len(paths)))]


def _parse_slideshow_paths(args) -> list[Path]:
    paths = _parse_paths(args, IMAGE_EXTENSIONS, required=False)
    audio_paths = [path for path in paths if path.suffix.lower().lstrip(".") in consts.AUDIO_ONLY_EXTENSIONS]
    if audio_paths:
        if args.audio:
            raise ValueError("Pass audio files with --audio instead of mixing them with image paths")
        if len(paths) != 1:
            raise ValueError("A slideshow accepts images plus one audio track")
        args.audio = [audio_paths[0]]
        return []
    return paths


def _create_black_slideshow(args, audio_duration: float) -> None:
    source = args.audio[0]
    destination = _destination(args, source, f"{source.stem}.mp4")
    destination_str = _prepare_destination(args, destination)
    if destination_str is None:
        return
    command = _black_audio_command(destination_str, args, audio_duration)
    _run(command, args)
    _verify_output(destination_str, args)
    if not args.simulate:
        print(destination_str)


def _validate_slideshow_paths(args, paths: list[Path]) -> None:
    if paths:
        return
    if not args.audio:
        raise ValueError("Provide at least one image or an audio track")
    if args.audio_duration or args.loop_images or args.hold_last_image or args.loop_audio:
        raise ValueError("Image duration modes require at least one image")


def images_to_video() -> None:
    args = parse_images_args()
    paths = _parse_slideshow_paths(args)
    _parse_audio_paths(args)
    _validate_images_args(args)
    _validate_slideshow_paths(args, paths)
    if args.shuffle:
        random.Random(args.seed).shuffle(paths)

    audio_duration = _audio_duration(args)
    if not paths:
        _create_black_slideshow(args, audio_duration)
        return

    if audio_duration is not None and not args.loop_audio:
        paths = _fit_images_to_audio(paths, args, audio_duration)
    output_duration = _slideshow_duration(len(paths), args)
    if args.audio and not args.loop_audio and audio_duration:
        output_duration = min(output_duration, audio_duration)

    destination = _destination(args, paths[0], "slideshow.mp4")
    destination_str = _prepare_destination(args, destination)
    if destination_str is None:
        return

    temp_path = None
    try:
        if args.crossfade_time:
            command = _crossfade_image_command(paths, destination_str, args, output_duration)
        elif args.motion != "none":
            command = _motion_image_command(paths, destination_str, args, output_duration)
        else:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as list_file:
                temp_path = list_file.name
                for path in paths:
                    escaped = str(path.resolve()).replace("\\", "\\\\").replace("'", "'\\''")
                    list_file.write(f"file '{escaped}'\nduration {args.picture_time:g}\n")
                escaped = str(paths[-1].resolve()).replace("\\", "\\\\").replace("'", "'\\''")
                list_file.write(f"file '{escaped}'\n")
            command = _concat_image_command(temp_path, destination_str, args, output_duration)

        _run(command, args)
        _verify_output(destination_str, args)
        if not args.simulate:
            print(destination_str)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def parse_concat_args() -> argparse.Namespace:
    parser = _parser(usage.video_concat)
    parser.add_argument("output")
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    return args


def _concat_file_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("\\", "\\\\").replace("'", "'\\''")
    return f"file '{escaped}'\n"


def video_concat() -> None:
    args = parse_concat_args()
    inputs = [Path(path).expanduser() for path in args.inputs]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        message = f"Input file not found: {', '.join(missing)}"
        raise FileNotFoundError(message)

    output = Path(args.output).expanduser()
    if output in inputs:
        raise ValueError("Output path must differ from every input path")
    destination = _prepare_destination(args, output)
    if destination is None:
        return

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as list_file:
            temp_path = list_file.name
            for path in inputs:
                list_file.write(_concat_file_line(path))

        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            temp_path,
            "-c",
            "copy",
            destination,
        ]
        _run(command, args)
        _verify_output(destination, args)
        if not args.simulate:
            print(destination)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
