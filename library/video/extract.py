import argparse, shlex, shutil, tempfile
from pathlib import Path

from library.utils import arggroups, argparse_utils, consts, devices, processes, shell_utils


USAGE = {
    "extract_audio": """library video extract audio PATH ... [--output PATH] [--all-audio] [--delete]

    Extract the first audio stream without re-encoding:

        library video extract audio video.mp4

    Extract every audio stream and optionally move the source to the trash after success:

        library video extract audio --all-audio --delete video.mkv
""",
    "extract_subtitles": """library video extract subtitles PATH ... [--stream N] [--format {srt,vtt,ass}] [--stdout]

    Extract an embedded subtitle stream to a sidecar file:

        library video extract subtitles video.mkv

    Print one embedded subtitle stream as SRT:

        library video extract subtitles --stdout --stream 1 video.mkv
""",
    "extract_scenes": """library video extract scenes PATH ... [--mode {video,images,contact-sheet}]

    Create a video containing scene changes:

        library video extract scenes video.mp4

    Extract scene-change images or a contact sheet:

        library video extract scenes --images video.mp4
        library video extract scenes --contact-sheet video.mp4
""",
    "extract_keyframes": """library video extract keyframes PATH ... [--mode {video,images,slow}] [--sort-similarity]

    Keep only keyframes in a stream-copy output:

        library video extract keyframes video.mp4

    Extract keyframe images or create an eight-times-slower keyframe video:

        library video extract keyframes --images video.mp4
        library video extract keyframes --slow video.mp4

    Sort keyframes by visual similarity before creating a video:

        library video extract keyframes --sort-similarity video.mp4
""",
}


VIDEO_EXTENSIONS = consts.VIDEO_EXTENSIONS | consts.IMAGE_ANIMATION_EXTENSIONS


def _base_parser(usage_text: str) -> argparse.ArgumentParser:
    parser = argparse_utils.ArgumentParser(usage=usage_text)
    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-dest", override_trash="trash")
    parser.add_argument(
        "--output",
        "-o",
        help="Output path for one input, or output directory when processing multiple inputs",
    )
    parser.add_argument("--output-dir", help="Output directory")
    arggroups.debug(parser)
    arggroups.paths_or_stdin(parser)
    return parser


def _parse(parser: argparse.ArgumentParser) -> argparse.Namespace:
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)
    return args


def _paths(args) -> list[Path]:
    paths = [Path(path).expanduser() for path in shell_utils.gen_paths(args, VIDEO_EXTENSIONS)]
    if not paths:
        processes.exit_error("No input paths passed in")
    for path in paths:
        if "://" in str(path):
            message = f"Video extraction requires a local path: {path}"
            raise ValueError(message)
    return paths


def _destination(args, source: Path, default_name: str, source_count: int) -> Path:
    if args.output_dir:
        return Path(args.output_dir).expanduser() / default_name

    if args.output:
        output = Path(args.output).expanduser()
        if source_count > 1 or output.is_dir():
            return output / default_name
        return output

    return source.with_name(default_name)


def _pattern_paths(destination: Path) -> list[Path]:
    pattern = destination.name.replace("%05d", "*").replace("%03d", "*")
    if pattern == destination.name:
        return []
    return list(destination.parent.glob(pattern))


def _prepare_destination(args, destination: Path) -> str | None:
    if not args.simulate:
        destination.parent.mkdir(parents=True, exist_ok=True)

    if "%" not in destination.name:
        if destination.exists() and args.file_over_file[-1] == arggroups.FileOverFile.SKIP:
            return None
        return devices.clobber_new_file(args, str(destination))

    existing = _pattern_paths(destination)
    if not existing:
        return str(destination)

    fallback = args.file_over_file[-1]
    if fallback == arggroups.FileOverFile.SKIP:
        return None
    if fallback == arggroups.FileOverFile.DELETE_DEST:
        if not args.simulate:
            for path in existing:
                path.unlink(missing_ok=True)
        return str(destination)
    if fallback == arggroups.FileOverFile.RENAME_DEST:
        original_name = destination.name
        prefix, marker, suffix = original_name.partition("%")
        counter = 1
        while existing:
            candidate = destination.with_name(f"{prefix}_{counter}{marker}{suffix}")
            existing = _pattern_paths(candidate)
            counter += 1
        return str(candidate)

    message = f"Unsupported file conflict strategy for generated files: {fallback}"
    raise ValueError(message)


def _run(command: list[str], args) -> None:
    if args.simulate:
        print(shlex.join(command))
        return
    processes.cmd(*command, limit_ram=True, nice=5, journald=False)


def _verify_output(destination: str, args) -> None:
    if args.simulate:
        return
    path = Path(destination)
    if "%" in path.name:
        if not _pattern_paths(path):
            message = f"FFmpeg produced no output files for {path}"
            raise RuntimeError(message)
    elif not path.exists():
        message = f"FFmpeg did not produce {path}"
        raise RuntimeError(message)


def _video_probe(path: Path):
    probe = processes.FFProbe(str(path))
    if not probe.video_streams:
        message = f"No video stream found: {path}"
        raise ValueError(message)
    return probe


def parse_audio_args() -> argparse.Namespace:
    parser = _base_parser(USAGE["extract_audio"])
    parser.add_argument(
        "--all-audio", action="store_true", help="Extract every audio stream instead of the default one"
    )
    parser.add_argument(
        "--delete",
        "--delete-original",
        dest="delete_original",
        action="store_true",
        help="Move the source to the trash after successful extraction",
    )
    return _parse(parser)


def extract_audio() -> None:
    args = parse_audio_args()
    paths = _paths(args)

    for source in paths:
        probe = processes.FFProbe(str(source))
        if not probe.audio_streams:
            message = f"No audio stream found: {source}"
            raise ValueError(message)

        destination = _destination(args, source, source.with_suffix(".mka").name, len(paths))
        destination_str = _prepare_destination(args, destination)
        if destination_str is None:
            continue

        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-i",
            str(source),
        ]
        if args.all_audio:
            command += ["-map", "0:a"]
        command += ["-vn", "-sn", "-dn", "-c:a", "copy", destination_str]
        _run(command, args)
        _verify_output(destination_str, args)

        if args.delete_original:
            shell_utils.trash(args, source, detach=False)
        if not args.simulate:
            print(destination_str)


def parse_subtitles_args() -> argparse.Namespace:
    parser = _base_parser(USAGE["extract_subtitles"])
    parser.add_argument("--stream", type=int, default=0, help="Subtitle stream number (default: 0)")
    parser.add_argument("--format", choices=["srt", "vtt", "ass"], default="srt")
    parser.add_argument(
        "--stdout",
        "--text",
        action="store_true",
        help="Write the selected subtitle stream to stdout instead of a sidecar file",
    )
    return _parse(parser)


def extract_subtitles() -> None:
    args = parse_subtitles_args()
    paths = _paths(args)
    if args.stdout and len(paths) != 1:
        raise ValueError("--stdout requires exactly one input path")

    for source in paths:
        probe = processes.FFProbe(str(source))
        if not probe.subtitle_streams:
            message = f"No subtitle stream found: {source}"
            raise ValueError(message)
        if args.stream < 0 or args.stream >= len(probe.subtitle_streams):
            message = f"Subtitle stream {args.stream} does not exist: {source}"
            raise ValueError(message)

        stream_index = probe.subtitle_streams[args.stream]["index"]
        codec = {"srt": "srt", "vtt": "webvtt", "ass": "ass"}[args.format]
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            f"0:{stream_index}",
            "-c:s",
            codec,
        ]

        if args.stdout:
            command += ["-f", args.format, "-"]
            result = processes.cmd(*command, journald=False)
            print(result.stdout, end="")
            continue

        destination = _destination(args, source, source.with_suffix(f".{args.format}").name, len(paths))
        destination_str = _prepare_destination(args, destination)
        if destination_str is None:
            continue
        command += ["-y", "-f", args.format, destination_str]
        _run(command, args)
        _verify_output(destination_str, args)
        if not args.simulate:
            print(destination_str)


def parse_scenes_args() -> argparse.Namespace:
    parser = _base_parser(USAGE["extract_scenes"])
    parser.add_argument("--mode", choices=["video", "images", "contact-sheet"], default="video")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--images", dest="mode", action="store_const", const="images")
    mode.add_argument("--contact-sheet", dest="mode", action="store_const", const="contact-sheet")
    parser.add_argument("--threshold", type=float, default=None, help="Scene-change threshold")
    parser.add_argument("--scale", default="1920:1080", help="Contact-sheet scale")
    parser.add_argument("--tile", default="6x5", help="Contact-sheet tile layout")
    return _parse(parser)


def extract_scenes() -> None:
    args = parse_scenes_args()
    paths = _paths(args)

    for source in paths:
        _video_probe(source)
        threshold = args.threshold if args.threshold is not None else (0.4 if args.mode == "contact-sheet" else 0.3)

        if args.mode == "video":
            default_name = f"{source.stem}.scenes.mkv"
        elif args.mode == "images":
            default_name = f"{source.stem}.scenes.%05d.jpg"
        else:
            default_name = f"{source.stem}.contactsheet_%03d.jpg"

        destination = _destination(args, source, default_name, len(paths))
        if args.mode != "video" and "%" not in destination.name:
            marker = "%05d" if args.mode == "images" else "%03d"
            destination = destination.with_name(f"{destination.stem}.{marker}{destination.suffix}")
        destination_str = _prepare_destination(args, destination)
        if destination_str is None:
            continue

        scene_filter = f"select='gt(scene,{threshold})'"
        if args.mode == "video":
            scene_filter += ",setpts=N/FRAME_RATE/TB"
        elif args.mode == "contact-sheet":
            scene_filter += f",scale={args.scale},tile={args.tile}"

        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-i",
            str(source),
            "-an",
            "-sn",
            "-vf",
            scene_filter,
        ]
        if args.mode == "images":
            command += ["-vsync", "vfr"]
        command.append(destination_str)
        _run(command, args)
        _verify_output(destination_str, args)
        if not args.simulate:
            print(destination_str)


def parse_keyframes_args() -> argparse.Namespace:
    parser = _base_parser(USAGE["extract_keyframes"])
    parser.add_argument("--mode", choices=["video", "images", "slow"], default="video")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--images", dest="mode", action="store_const", const="images")
    mode.add_argument("--slow", dest="mode", action="store_const", const="slow")
    parser.add_argument("--slow-factor", type=float, default=8, help="Slow-motion factor (default: 8)")
    parser.add_argument(
        "--sort-similarity",
        "--similarity-sort",
        "--visual-similarity",
        "--sort",
        dest="sort_similarity",
        action="store_true",
        help="Sort keyframes by visual similarity before creating the output video",
    )
    parser.add_argument(
        "--sort-neighbors",
        "--n-neighbors",
        dest="sort_neighbors",
        type=int,
        default=200,
        help="Number of nearest neighbors considered by visual similarity sorting (default: 200)",
    )
    parser.add_argument(
        "--sort-trees",
        "--tree-count",
        dest="sort_trees",
        type=int,
        default=30,
        help="Number of Annoy trees used by visual similarity sorting (default: 30)",
    )
    args = _parse(parser)
    if args.sort_neighbors < 1:
        parser.error("--sort-neighbors must be at least 1")
    if args.sort_trees < 1:
        parser.error("--sort-trees must be at least 1")
    if args.sort_similarity and args.mode != "video":
        parser.error("--sort-similarity is only supported with video keyframe output")
    return args


def _keyframe_base_command(source: Path) -> list[str]:
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-i",
        str(source),
    ]


def _keyframe_image_command(source: Path, destination: str) -> list[str]:
    return [
        *_keyframe_base_command(source),
        "-vf",
        "select='eq(pict_type,PICT_TYPE_I)'",
        "-vsync",
        "vfr",
        destination,
    ]


def _keyframe_video_command(source: Path, destination: str, *, streams: bool = True) -> list[str]:
    command = [
        *_keyframe_base_command(source),
        "-c",
        "copy",
        "-bsf:v",
        "noise=drop=not(key)",
    ]
    if not streams:
        command += ["-an", "-sn"]
    return [*command, *(["-f", "matroska"] if not streams else []), destination]


def _slow_keyframe_commands(source: Path, destination: str, slow_factor: float, temp_path: str) -> list[list[str]]:
    first_command = _keyframe_video_command(source, temp_path, streams=False)
    second_command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "matroska",
        "-i",
        temp_path,
        "-vf",
        f"setpts=N/FRAME_RATE/TB*{slow_factor:g}",
        destination,
    ]
    return [first_command, second_command]


def _load_similarity_tools():
    try:
        import numpy as np
        from annoy import AnnoyIndex
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Visual-similarity sorting requires the optional numpy, annoy, and Pillow dependencies"
        ) from exc
    return np, AnnoyIndex, Image


def _frame_vector(path: Path, np, image_library):
    with image_library.open(path) as image_file:
        image = image_file.resize((64, 64)).convert("L")
        return np.array(image).flatten().astype("float32") / 255.0


def similarity_order(vectors, annoy_index, n_neighbors: int, tree_count: int) -> list[int]:
    if not vectors:
        return []

    index = annoy_index(len(vectors[0]), "angular")
    for item, vector in enumerate(vectors):
        index.add_item(item, vector)
    index.build(tree_count)

    current = 0
    order = [current]
    visited = {current}
    while len(order) < len(vectors):
        neighbors = index.get_nns_by_item(current, min(n_neighbors, len(vectors)), include_distances=True)[0]
        next_item = next((item for item in neighbors if item not in visited), None)
        if next_item is None:
            next_item = next(item for item in range(len(vectors)) if item not in visited)
        order.append(next_item)
        visited.add(next_item)
        current = next_item
    return order


def _sorted_keyframe_video_command(frame_pattern: str, destination: str) -> list[str]:
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-framerate",
        "3",
        "-i",
        frame_pattern,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "20",
        destination,
    ]


def _sort_keyframes_by_similarity(args, source: Path, destination: str) -> None:
    destination_path = Path(destination)
    if args.simulate:
        frame_pattern = str(destination_path.parent / f".{destination_path.stem}.keyframe.%05d.png")
        _run(_keyframe_image_command(source, frame_pattern), args)
        _run(_sorted_keyframe_video_command(frame_pattern, destination), args)
        return

    np, annoy_index, image_library = _load_similarity_tools()
    with tempfile.TemporaryDirectory(prefix=".library-keyframes-", dir=str(destination_path.parent)) as temp_dir:
        temp_path = Path(temp_dir)
        frame_pattern = str(temp_path / "frame_%05d.png")
        _run(_keyframe_image_command(source, frame_pattern), args)
        frame_paths = sorted(temp_path.glob("frame_*.png"))
        if not frame_paths:
            message = f"FFmpeg produced no keyframes for {source}"
            raise RuntimeError(message)

        vectors = [_frame_vector(path, np, image_library) for path in frame_paths]
        order = similarity_order(vectors, annoy_index, args.sort_neighbors, args.sort_trees)
        sorted_pattern = temp_path / "sorted_frame_%05d.png"
        for output_index, frame_index in enumerate(order):
            output_path = temp_path / f"sorted_frame_{output_index:05d}.png"
            shutil.copyfile(frame_paths[frame_index], output_path)

        _run(_sorted_keyframe_video_command(str(sorted_pattern), destination), args)


def _run_slow_keyframes(args, source: Path, destination: str) -> None:
    if args.simulate:
        for command in _slow_keyframe_commands(source, destination, args.slow_factor, "KEYFRAMES.mkv"):
            _run(command, args)
        return

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as temp:
            temp_path = temp.name
        for command in _slow_keyframe_commands(source, destination, args.slow_factor, temp_path):
            _run(command, args)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def extract_keyframes() -> None:
    args = parse_keyframes_args()
    paths = _paths(args)

    for source in paths:
        _video_probe(source)
        default_names = {
            "images": f"{source.stem}.%05d.jpg",
            "slow": f"{source.stem}.keys.mkv",
            "video": f"{source.stem}.{'sortedkeys.mp4' if args.sort_similarity else 'quickkeys.mkv'}",
        }
        default_name = default_names[args.mode]

        destination = _destination(args, source, default_name, len(paths))
        if args.mode == "images" and "%" not in destination.name:
            destination = destination.with_name(f"{destination.stem}.%05d{destination.suffix}")
        if args.sort_similarity and "%" in destination.name:
            raise ValueError("--sort-similarity requires a single output path")
        destination_str = _prepare_destination(args, destination)
        if destination_str is None:
            continue

        if args.sort_similarity:
            _sort_keyframes_by_similarity(args, source, destination_str)
        elif args.mode == "images":
            _run(_keyframe_image_command(source, destination_str), args)
        elif args.mode == "video":
            _run(_keyframe_video_command(source, destination_str), args)
        elif args.mode == "slow":
            _run_slow_keyframes(args, source, destination_str)

        _verify_output(destination_str, args)
        if not args.simulate:
            print(destination_str)
