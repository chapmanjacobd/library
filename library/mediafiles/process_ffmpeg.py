import argparse, os, shlex, subprocess
from pathlib import Path

from library import usage
from library.data import ffmpeg_errors
from library.mediafiles import process_image
from library.utils import arggroups, argparse_utils, consts, devices, nums, path_utils, processes, web
from library.utils.arg_utils import args_override
from library.utils.file_utils import gen_paths
from library.utils.log_utils import log
from library.utils.web import WebPath


def parse_args(defaults_override=None) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_ffmpeg)
    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-dest")
    parser.add_argument("--clean-path", action=argparse.BooleanOptionalAction, default=False, help="Clean output path")
    arggroups.process_ffmpeg(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)

    parser.set_defaults(**(defaults_override or {}))
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.process_ffmpeg_post(args)

    return args


def is_animation_from_probe(probe) -> bool | None:
    if probe.audio_streams:
        return True
    for stream in probe.video_streams:
        frames = nums.safe_int(stream.get("nb_frames"))
        if frames is None:
            r = processes.cmd(
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_read_frames",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                probe.path,
            )
            frames = nums.safe_int(r.stdout)
            if frames is None:  # "N/A", corrupt file
                return None

        if frames > 1:
            return True

    return False


def process_path(args, path, include_timecode=False, subtitle_streams_unsupported=False, **kwargs) -> str | None:
    if kwargs:
        args = args_override(args, kwargs)

    output_path = web.gen_output_path(args, path, target_extension=".XXXXXXX")  # max target ext len

    path, output_path = devices.clobber(args, path, output_path)
    if path is None:
        return output_path

    path = WebPath(path)
    output_path = Path(output_path)

    output_path.parent.mkdir(exist_ok=True, parents=True)

    if args.simulate and consts.PYTEST_RUNNING:
        print("ffmpeg", path, output_path)
        return str(path)

    try:
        original_stats = path.stat()
    except FileNotFoundError:
        log.error("File not found: %s", path)
        return None

    try:
        probe = processes.FFProbe(path)
    except processes.UnplayableFile:
        if args.delete_unplayable:
            log.warning("Deleting unplayable (ffprobe): %s", path)
            path.unlink()
            return None
        raise

    if not probe.streams:
        log.error("No media streams found: %s", path)
        if args.delete_unplayable:
            log.warning("Deleting unplayable (no streams): %s", path)
            path.unlink()
            return None
        return str(path)

    if path_utils.ext(path) in consts.IMAGE_ANIMATION_EXTENSIONS:
        is_animation = is_animation_from_probe(probe)
        if is_animation is None:
            if args.delete_unplayable:
                log.warning("Deleting unplayable (zero frames): %s", path)
                path.unlink()
                return None
            return str(path)
        elif not is_animation:
            return process_image.process_path(args, path)

    video_stream = next((s for s in probe.video_streams), None)
    audio_stream = next((s for s in probe.audio_streams), None)
    subtitle_stream = next((s for s in probe.subtitle_streams), None)
    album_art_stream = next((s for s in probe.album_art_streams), None)
    if not video_stream:
        if not args.audio_only:
            log.warning("No video stream found: %s", path)
        if args.delete_no_video:
            path.unlink()
            return None
    if not audio_stream:
        log.warning("No audio stream found: %s", path)
        if args.delete_no_audio:
            path.unlink()
            return None

    if video_stream and (video_stream.get("codec_name") or "") == "av1":
        log.info("Video is already AV1: %s", path)
        return str(path)
    elif (not video_stream or args.audio_only) and audio_stream and (audio_stream.get("codec_name") or "") == "opus":
        log.info("Audio is already Opus: %s", path)
        return str(path)

    if video_stream and not args.audio_only:
        output_suffix = ".av1.mkv"
    elif audio_stream:
        output_suffix = ".mka"
    else:
        output_suffix = ".gif.mkv"
    output_path = output_path.with_suffix(output_suffix)

    path, output_path = devices.clobber(args, path, output_path)
    if path is None:
        return output_path
    path = Path(path)
    output_path = Path(output_path)

    ff_opts: list[str] = []

    if video_stream:
        for s in probe.video_streams:
            ff_opts.extend(["-map", f'0:{s["index"]}'])

        if args.keyframes:
            ff_opts.extend(["-c:v", "copy", "-bsf:v", "noise=drop=not(key)"])
        else:
            ff_opts.extend(
                [
                    "-c:v",
                    "libsvtav1",
                    "-preset",
                    args.preset,
                    "-crf",
                    args.crf,
                    "-pix_fmt",
                    "yuv420p10le",
                    "-svtav1-params",
                    "tune=0:enable-overlays=1",
                ]
            )

            video_filters = []
            if probe.fps and probe.fps > 240:
                log.info("fps>240 is not supported by AV1 and it seems suspect. Ignoring metadata %s", path)
                frames = nums.safe_int(
                    processes.cmd(
                        "ffprobe",
                        "-v",
                        "fatal",
                        "-select_streams",
                        "v:0",
                        "-count_frames",
                        "-show_entries",
                        "stream=nb_read_frames",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        path,
                    ).stdout
                )
                if frames and probe.duration:
                    actual_fps = frames / probe.duration
                    video_filters.append(f"fps={actual_fps}")

            width = int(video_stream.get("width"))
            height = int(video_stream.get("height"))

            if width > (args.max_video_width * (1 + args.max_width_buffer)):
                video_filters.append(f"scale={args.max_video_width}:-2")
            elif height > (args.max_video_height * (1 + args.max_height_buffer)):
                video_filters.append(f"scale=-2:{args.max_video_height}")
            else:  # make sure input raster is even for YUV_420 colorspace
                video_filters.append("pad='if(mod(iw,2),iw+1,iw)':'if(mod(ih,2),ih+1,ih)'")

            ff_opts.extend(["-vf", ",".join(video_filters)])

    elif album_art_stream:
        ff_opts.extend(["-map", "0:v", "-c:v", "copy"])

    is_split = bool(audio_stream)
    if audio_stream:
        ff_opts.extend(["-map", "0:a"])

        channels = audio_stream.get("channels") or 2
        bitrate = int(audio_stream.get("bit_rate") or probe.format.get("bit_rate") or 256000)
        source_rate = int(audio_stream.get("sample_rate") or 44100)

        duration = float(audio_stream.get("duration") or probe.format.get("duration") or 0)
        is_split = args.always_split or (args.split_longer_than and duration > args.split_longer_than)

        try:
            assert bitrate > 0
            assert channels > 0
            assert source_rate > 0
        except AssertionError:
            log.exception("Broken file or audio format misdetected: %s", path)
            if args.delete_no_audio:
                path.unlink()
                return None
        else:
            if channels == 1:
                ff_opts.extend(["-ac", "1"])
            else:
                ff_opts.extend(["-ac", "2"])

            if bitrate >= 256000:
                ff_opts.extend(["-b:a", "128k"])
            else:
                ff_opts.extend(["-b:a", "64k", "-frame_duration", "40", "-apply_phase_inv", "0"])

            if source_rate >= 44100:
                opus_rate = 48000
            elif source_rate >= 22050:
                opus_rate = 24000
            else:
                opus_rate = 16000
            ff_opts.extend(["-c:a", "libopus", "-ar", str(opus_rate), "-af", "loudnorm=i=-18:tp=-3:lra=17"])

        if is_split:
            try:
                result = subprocess.check_output(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-v",
                        "warning",
                        "-i",
                        path,
                        "-af",
                        "silencedetect=-55dB:d=0.3,ametadata=mode=print:file=-:key=lavfi.silence_start",
                        "-vn",
                        "-sn",
                        "-f",
                        "s16le",
                        "-y",
                        "/dev/null",
                    ]
                )
            except subprocess.CalledProcessError:
                log.error("Splits could not be identified. Likely broken file: %s", path)
                is_split = False
            else:
                splits = result.decode().split("\n")
                splits = [line.split("=")[1] for line in splits if "lavfi.silence_start" in line]

                prev = 0.0
                final_splits = []
                for split in splits:
                    split = float(split)
                    if (split - prev) >= args.min_split_segment:  # type: ignore
                        final_splits.append(str(split))
                        prev = split

                if final_splits:
                    output_path = path.with_suffix(".%03d" + output_suffix)
                    final_splits = ",".join(final_splits)
                    print(f"Splitting {path} at points: {final_splits}")
                    ff_opts.extend(["-f", "segment", "-segment_times", final_splits])
                else:
                    is_split = False

    if subtitle_stream:
        if subtitle_streams_unsupported:
            ff_opts.extend(["-map", "0:s"])
        else:
            ff_opts.extend(["-map", "0:s", "-c:s", "copy"])

    if include_timecode:
        ff_opts.extend(["-map", "0:t"])

    output_path.parent.mkdir(exist_ok=True, parents=True)
    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)

    command = [
        "ffmpeg",
        "-nostdin",
        *(
            ["-v", "9", "-loglevel", "99"]
            if args.verbose > consts.LOG_DEBUG_SQL
            else ["-hide_banner", "-loglevel", "warning"]
        ),
        "-y",
        "-i",
        str(path),
        "-movflags",
        "use_metadata_tags",
        *ff_opts,
        # "-copy_unknown",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-dn",
        "-max_interleave_delta",
        "0",
        str(output_path),
    ]

    if args.simulate:
        print(shlex.join(command))
        return str(path)

    is_file_error = False
    try:
        processes.cmd(*command, limit_ram=True)
    except subprocess.CalledProcessError as e:
        error_log = e.stderr.splitlines()
        is_unsupported_subtitle = any(ffmpeg_errors.unsupported_subtitle_error.match(l) for l in error_log)
        is_unsupported = any(ffmpeg_errors.unsupported_error.match(l) for l in error_log)
        is_file_error = any(ffmpeg_errors.file_error.match(l) for l in error_log)
        is_env_error = any(ffmpeg_errors.environment_error.match(l) for l in error_log)

        if is_env_error:
            raise
        elif is_file_error:
            pass
        elif is_unsupported_subtitle and not subtitle_streams_unsupported:
            output_path.unlink(missing_ok=True)  # Remove transcode attempt, if any
            return process_path(
                args, path, include_timecode=include_timecode, subtitle_streams_unsupported=True, **kwargs
            )
        elif is_unsupported:
            output_path.unlink(missing_ok=True)  # Remove transcode attempt, if any
            return str(path)
        else:
            raise

    if is_split:
        output_path = output_path.with_name(
            output_path.name.replace(".%03d", ".000")
        )  # TODO: support / return multiple paths...

    delete_larger = args.delete_larger
    delete_transcode = False

    if not output_path.exists():
        return str(path) if path.exists() else None
    elif not path.exists():
        return str(output_path)

    output_stats = output_path.stat()

    # Never set delete_larger to True. That setting comes from args and it is default True
    transcode_invalid = False
    if output_stats.st_size == 0:
        transcode_invalid = True
    elif delete_larger and output_stats.st_size > original_stats.st_size:
        delete_larger = False
        delete_transcode = True
    else:
        try:
            transcode_probe = processes.FFProbe(output_path)
        except (TimeoutError, subprocess.TimeoutExpired):
            log.error(f"FFProbe timed out. {output_path}")
            transcode_invalid = True
        except processes.UnplayableFile:
            transcode_invalid = True
        else:
            if not transcode_probe.streams:
                transcode_invalid = True
            elif not transcode_probe.duration:
                transcode_invalid = True
            elif args.delete_unplayable and is_file_error:
                pass  # if the original file is broken but the transcode is somewhat valid, don't compare duration
            elif path_utils.ext(path).lower() in consts.SKIP_MEDIA_CHECK:
                pass  # duration metadata for these source formats is usually incorrect
            elif nums.percentage_difference(probe.duration, transcode_probe.duration) > 5.0:
                transcode_invalid = True
    if transcode_invalid:
        if args.delete_unplayable:
            delete_transcode = False
        else:
            delete_larger = False
            delete_transcode = True
    if video_stream and args.audio_only and not args.no_preserve_video:
        delete_larger = False

    if delete_transcode:
        output_path.unlink()
        return str(path)
    elif delete_larger:
        path.unlink()

    os.utime(output_path, (original_stats.st_atime, original_stats.st_mtime))
    return str(output_path)


def process_ffmpeg(defaults_override=None):
    args = parse_args(defaults_override)

    for path in gen_paths(args, consts.AUDIO_ONLY_EXTENSIONS | consts.VIDEO_EXTENSIONS):
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise


def process_audio():
    process_ffmpeg({"audio_only": True})
