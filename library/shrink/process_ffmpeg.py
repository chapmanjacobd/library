import argparse, os, shlex, subprocess
from pathlib import Path

from library import usage
from library.data import ffmpeg_errors
from library.shrink import process_image
from library.utils import arggroups, argparse_utils, consts, devices, nums, path_utils, processes, web
from library.utils.arg_utils import args_override
from library.utils.log_utils import log
from library.utils.shell_utils import gen_paths
from library.utils.web import WebPath

MAX_SUPPORTED_FPS = 240
SBS_ASPECT_RATIO_MIN = 1.9
SBS_ASPECT_RATIO_MAX = 2.1
SBS_MIN_WIDTH = 4_500
OU_ASPECT_RATIO_MIN = 0.9
OU_ASPECT_RATIO_MAX = 1.1
OU_MIN_HEIGHT = 2_600
HIGH_AUDIO_BITRATE = 256_000
HIGH_AUDIO_SAMPLE_RATE = 44_100
MEDIUM_AUDIO_SAMPLE_RATE = 22_050
MAX_DURATION_DIFFERENCE = 5.0


def parse_args(defaults_override=None) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.process_ffmpeg)
    arggroups.clobber(parser)
    parser.set_defaults(file_over_file="delete-dest")
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
                nice=6,
                journald=False,
            )
            frames = nums.safe_int(r.stdout)
            if frames is None:  # "N/A", corrupt file
                return None

        if frames > 1:
            return True

    return False


def result_paths(result: str | list[str] | Path | None) -> list[str]:
    if result is None:
        return []
    if isinstance(result, list):
        return [str(path) for path in result]
    return [str(result)]


def segment_paths(output_path: Path, segment_count: int) -> list[Path]:
    if "%03d" not in output_path.name:
        return [output_path]
    return [output_path.with_name(output_path.name.replace("%03d", f"{index:03d}")) for index in range(segment_count)]


_PROCESS_CONTINUE = object()


def _probe_input(args, path):
    try:
        original_stats = path.stat()
    except FileNotFoundError:
        log.error("File not found: %s", path)
        return None, None

    try:
        probe = processes.FFProbe(path)
    except processes.UnplayableFileError:
        if args.delete_unplayable:
            log.warning("Deleting unplayable (ffprobe): %s", path)
            path.unlink(missing_ok=True)
            return original_stats, None
        raise
    return original_stats, probe


def _handle_animation(args, path, probe):
    if path_utils.ext(path) not in consts.IMAGE_ANIMATION_EXTENSIONS:
        return _PROCESS_CONTINUE
    is_animation = is_animation_from_probe(probe)
    if is_animation is None:
        if args.delete_unplayable:
            log.warning("Deleting unplayable (zero frames): %s", path)
            path.unlink(missing_ok=True)
            return None
        return str(path)
    if not is_animation:
        return process_image.process_path(args, path)
    return _PROCESS_CONTINUE


def _validate_video_stream(args, path, video_stream):
    if video_stream:
        return _PROCESS_CONTINUE
    if args.delete_no_video:
        path.unlink(missing_ok=True)
        return None
    if args.video_only:
        return str(path)
    if not args.audio_only and path_utils.ext(path) not in consts.AUDIO_ONLY_EXTENSIONS:
        log.warning("No video stream found: %s", path)
    return _PROCESS_CONTINUE


def _validate_audio_stream(args, path, audio_stream):
    if audio_stream:
        return _PROCESS_CONTINUE
    if args.delete_no_audio:
        path.unlink(missing_ok=True)
        return None
    if args.audio_only:
        return str(path)
    if not args.video_only and path_utils.ext(path) not in consts.IMAGE_ANIMATION_EXTENSIONS:
        log.warning("No audio stream found: %s", path)
    return _PROCESS_CONTINUE


def _validate_stream_codecs(args, path, video_stream, audio_stream):
    if video_stream and not args.audio_only and (video_stream.get("codec_name") or "") == "av1":
        log.info("Video is already AV1: %s", path)
        return str(path)
    if (not video_stream or args.audio_only) and audio_stream and (audio_stream.get("codec_name") or "") == "opus":
        log.info("Audio is already Opus: %s", path)
        return str(path)
    return _PROCESS_CONTINUE


def _validate_streams(args, path, video_stream, audio_stream):
    for validator, stream in ((_validate_video_stream, video_stream), (_validate_audio_stream, audio_stream)):
        result = validator(args, path, stream)
        if result is not _PROCESS_CONTINUE:
            return result
    return _validate_stream_codecs(args, path, video_stream, audio_stream)


def _stereo_mode(width, height, video_stream):
    aspect_ratio = width / height if height else 0
    tags = video_stream.get("tags") or {}
    stereo_tag = (tags.get("stereo_mode") or tags.get("StereoMode") or "").lower()
    if stereo_tag in {"left_right", "side_by_side", "sbs"}:
        return "sbs"
    if stereo_tag in {"top_bottom", "over_under", "tb", "ou"}:
        return "ou"
    if SBS_ASPECT_RATIO_MIN <= aspect_ratio <= SBS_ASPECT_RATIO_MAX and width >= SBS_MIN_WIDTH:
        return "sbs"
    if OU_ASPECT_RATIO_MIN <= aspect_ratio <= OU_ASPECT_RATIO_MAX and height >= OU_MIN_HEIGHT:
        return "ou"
    return None


def _sbs_filter(args, width, height):
    per_eye_width = width // 2
    target_eye_width = args.max_video_width
    target_total_width = target_eye_width * 2
    if per_eye_width > target_eye_width * (1 + args.max_width_buffer):
        return f"scale={target_total_width}:-2"
    if height > args.max_video_height * (1 + args.max_height_buffer):
        return f"scale=-2:{args.max_video_height}"
    return None


def _ou_filter(args, width, height):
    per_eye_height = height // 2
    target_eye_height = args.max_video_height
    target_total_height = target_eye_height * 2
    if per_eye_height > target_eye_height * (1 + args.max_height_buffer):
        return f"scale=-2:{target_total_height}"
    if width > args.max_video_width * (1 + args.max_width_buffer):
        return f"scale={args.max_video_width}:-2"
    return None


def _stereo_filter(args, width, height, stereo_mode):
    if stereo_mode == "sbs":
        return _sbs_filter(args, width, height) or "pad='if(mod(iw,2),iw+1,iw)':'if(mod(ih,2),ih+1,ih)'"
    if stereo_mode == "ou":
        return _ou_filter(args, width, height) or "pad='if(mod(iw,2),iw+1,iw)':'if(mod(ih,2),ih+1,ih)'"
    if width > args.max_video_width * (1 + args.max_width_buffer):
        return f"scale={args.max_video_width}:-2"
    if height > args.max_video_height * (1 + args.max_height_buffer):
        return f"scale=-2:{args.max_video_height}"
    return "pad='if(mod(iw,2),iw+1,iw)':'if(mod(ih,2),ih+1,ih)'"


def _video_filters(args, path, probe, video_stream):
    filters = []
    if probe.fps and probe.fps > MAX_SUPPORTED_FPS:
        log.info("fps>%s is not supported by AV1 and it seems suspect. Ignoring metadata %s", MAX_SUPPORTED_FPS, path)
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
                nice=5,
                journald=False,
            ).stdout
        )
        if frames and probe.duration:
            filters.append(f"fps={frames / probe.duration}")

    width = int(video_stream.get("width"))
    height = int(video_stream.get("height"))
    filters.append(_stereo_filter(args, width, height, _stereo_mode(width, height, video_stream)))
    return filters


def _add_video_options(args, path, probe, video_stream, ff_opts):
    for stream in probe.video_streams:
        ff_opts.extend(["-map", f'0:{stream["index"]}'])
    if args.keyframes:
        ff_opts.extend(["-c:v", "copy", "-bsf:v", "noise=drop=not(key)"])
        return
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
    ff_opts.extend(["-vf", ",".join(_video_filters(args, path, probe, video_stream))])


def _detect_splits(args, path):
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
        return None
    splits = result.decode().split("\n")
    splits = [line.split("=")[1] for line in splits if "lavfi.silence_start" in line]
    prev = 0.0
    final_splits = []
    for raw_split in splits:
        split_time = float(raw_split)
        if (split_time - prev) >= args.min_split_segment:  # type: ignore
            final_splits.append(str(split_time))
            prev = split_time
    return final_splits


def _add_audio_codec_options(args, path, probe, audio_stream, ff_opts):
    channels = audio_stream.get("channels") or 2
    bitrate = int(audio_stream.get("bit_rate") or probe.format.get("bit_rate") or 256000)
    source_rate = int(audio_stream.get("sample_rate") or 44100)
    try:
        assert bitrate > 0
        assert channels > 0
        assert source_rate > 0
    except AssertionError:
        log.exception("Broken file or audio format misdetected: %s", path)
        if args.delete_no_audio:
            path.unlink(missing_ok=True)
        return False

    ff_opts.extend(["-ac", "1" if channels == 1 else "2"])
    if bitrate >= HIGH_AUDIO_BITRATE:
        ff_opts.extend(["-b:a", "128k"])
    else:
        ff_opts.extend(["-b:a", "64k", "-frame_duration", "40", "-apply_phase_inv", "0"])
    opus_rate = 48000 if source_rate >= HIGH_AUDIO_SAMPLE_RATE else 24000 if source_rate >= MEDIUM_AUDIO_SAMPLE_RATE else 16000
    ff_opts.extend(["-c:a", "libopus", "-ar", str(opus_rate), "-af", "loudnorm=i=-18:tp=-3:lra=17"])
    return True


def _add_audio_options(args, path, probe, audio_stream, video_stream, ff_opts):
    ff_opts.extend(["-map", "0:a"])
    duration = float(audio_stream.get("duration") or probe.format.get("duration") or 0)
    is_split = args.always_split or (not video_stream and args.split_longer_than and duration > args.split_longer_than)
    _add_audio_codec_options(args, path, probe, audio_stream, ff_opts)
    if not is_split:
        return False, None
    final_splits = _detect_splits(args, path)
    if not final_splits:
        return False, None
    segment_times = ",".join(final_splits)
    ff_opts.extend(["-f", "segment", "-segment_times", segment_times])
    return True, len(final_splits) + 1


def _add_subtitle_options(probe, path, ff_opts):
    text_subs = {
        "ass", "ssa", "subrip", "srt", "mov_text", "webvtt", "text", "utf8", "arib_caption",
        "libaribcaption", "libaribb24", "libzvbi_teletextdec", "dvb_teletext", "cc_dec", "jacosub",
        "microdvd", "mpl2", "pjs", "realtext", "sami", "stl", "subviewer", "subviewer1", "vplayer",
    }
    image_subs = {"dvd_subtitle", "dvdsub", "pgssub", "hdmv_pgs_subtitle", "xsub", "dvb_subtitle", "dvbsub"}
    mkv_text_subs = {"subrip", "srt", "ass", "ssa", "webvtt"}
    mkv_image_subs = {"pgssub", "hdmv_pgs_subtitle", "dvd_subtitle", "vobsub"}
    for stream in probe.subtitle_streams:
        codec = stream.get("codec_name", "").lower()
        index = stream.get("index")
        if not codec:
            log.warning("%s: Subtitle codec not found %s", path, stream)
            continue
        if codec in mkv_text_subs or codec in mkv_image_subs:
            ff_opts.extend(["-map", f"0:{index}", "-c:s", "copy"])
        elif codec in text_subs:
            ff_opts.extend(["-map", f"0:{index}", "-c:s", "srt"])
        elif codec in image_subs:
            ff_opts.extend(["-map", f"0:{index}", "-c:s", "pgssub"])
        else:
            log.warning("%s: Subtitle codec unknown %s", path, stream)
            return False
    return True


def _build_ffmpeg_options(
    args, path, probe, output_path, video_stream, audio_stream, subtitle_stream, album_art_stream, include_timecode
):
    ff_opts = []
    if video_stream:
        _add_video_options(args, path, probe, video_stream, ff_opts)
    elif album_art_stream:
        ff_opts.extend(["-map", "0:v", "-c:v", "copy"])

    is_split = False
    segment_count = 1
    if audio_stream:
        is_split, detected_segment_count = _add_audio_options(args, path, probe, audio_stream, video_stream, ff_opts)
        if detected_segment_count:
            segment_count = detected_segment_count
            output_path = output_path.with_name(f"{output_path.stem}.%03d{output_path.suffix}")
            log.info("Splitting %s into %s segments", path, segment_count)

    if subtitle_stream and not _add_subtitle_options(probe, path, ff_opts):
        return ff_opts, is_split, segment_count, output_path, str(path)
    if include_timecode:
        ff_opts.extend(["-map", "0:t"])
    return ff_opts, is_split, segment_count, output_path, None


def _output_suffix(video_stream, audio_stream):
    if video_stream:
        return ".av1.mkv"
    if audio_stream:
        return ".mka"
    return ".gif.mkv"


def _run_ffmpeg(_args, command, output_paths):
    try:
        processes.cmd(*command, limit_ram=True, nice=10)
    except subprocess.CalledProcessError as excinfo:
        error_log = excinfo.stderr.splitlines()
        is_unsupported = any(ffmpeg_errors.unsupported_error.match(line) for line in error_log)
        is_file_error = any(ffmpeg_errors.file_error.match(line) for line in error_log)
        is_env_error = any(ffmpeg_errors.environment_error.match(line) for line in error_log)
        if is_env_error:
            raise
        if is_file_error:
            return True
        if is_unsupported:
            for generated_path in output_paths:
                generated_path.unlink(missing_ok=True)
            return False
        raise
    return None


def _validate_output_paths(path, output_paths, is_split):
    if not all(generated_path.exists() for generated_path in output_paths):
        for generated_path in output_paths:
            generated_path.unlink(missing_ok=True)
        return str(path) if path.exists() else None
    if not path.exists():
        results = [str(generated_path) for generated_path in output_paths]
        return results if is_split else results[0]
    return _PROCESS_CONTINUE


def _transcode_invalid(args, path, probe, output_paths, is_file_error):
    transcode_invalid = any(generated_path.stat().st_size == 0 for generated_path in output_paths)
    if transcode_invalid:
        return True
    try:
        transcode_probes = [processes.FFProbe(generated_path) for generated_path in output_paths]
    except (TimeoutError, subprocess.TimeoutExpired):
        log.error("FFProbe timed out. %s", output_paths)
        transcode_invalid = True
    except processes.UnplayableFileError:
        transcode_invalid = True
    else:
        transcode_invalid = any(not transcode_probe.streams for transcode_probe in transcode_probes)
        transcode_invalid |= any(not transcode_probe.duration for transcode_probe in transcode_probes)
        if not transcode_invalid and not (args.delete_unplayable and is_file_error):
            transcode_invalid = path_utils.ext(path).lower() not in consts.SKIP_MEDIA_CHECK and (
                nums.percentage_difference(probe.duration, sum(p.duration for p in transcode_probes))
                > MAX_DURATION_DIFFERENCE
            )
    return transcode_invalid


def _finalize_transcode(args, path, probe, video_stream, output_paths, original_stats, is_split, is_file_error):
    delete_larger = args.delete_larger
    delete_original = getattr(args, "delete_original", False)
    delete_transcode = False
    output_stats = [generated_path.stat() for generated_path in output_paths]
    if any(stats.st_size == 0 for stats in output_stats):
        transcode_invalid = True
    elif delete_larger and not delete_original and sum(stats.st_size for stats in output_stats) > original_stats.st_size:
        delete_larger = False
        delete_transcode = True
        transcode_invalid = False
    else:
        transcode_invalid = _transcode_invalid(args, path, probe, output_paths, is_file_error)
    if transcode_invalid:
        delete_original = False
        if args.delete_unplayable:
            delete_transcode = False
        else:
            delete_larger = False
            delete_transcode = True
    if video_stream and args.audio_only and not args.no_preserve_video:
        delete_larger = False

    try:
        if delete_transcode:
            for generated_path in output_paths:
                generated_path.unlink(missing_ok=True)
            return str(path)
        if delete_larger or delete_original:
            path.unlink(missing_ok=True)
    except FileNotFoundError:
        return None

    for generated_path in output_paths:
        os.utime(generated_path, (original_stats.st_atime, original_stats.st_mtime))
    results = [str(generated_path) for generated_path in output_paths]
    return results if is_split else results[0]


def _prepare_process_input(args, path, output_path):
    early_result = _PROCESS_CONTINUE
    path, output_path = devices.clobber(args, path, output_path)
    original_stats = probe = None
    video_stream = audio_stream = subtitle_stream = album_art_stream = None

    if path is None:
        early_result = output_path
    else:
        path = WebPath(path)
        output_path = Path(output_path)
        if not args.simulate:
            output_path.parent.mkdir(exist_ok=True, parents=True)
        original_stats, probe = _probe_input(args, path)
        if original_stats is None or probe is None:
            early_result = None
        elif not probe.streams:
            log.error("No media streams found: %s", path)
            if args.delete_unplayable:
                log.warning("Deleting unplayable (no streams): %s", path)
                path.unlink(missing_ok=True)
            early_result = None if args.delete_unplayable else str(path)
        else:
            animation_result = _handle_animation(args, path, probe)
            if animation_result is not _PROCESS_CONTINUE:
                early_result = animation_result
            else:
                video_stream = next((stream for stream in probe.video_streams), None)
                audio_stream = next((stream for stream in probe.audio_streams), None)
                subtitle_stream = next((stream for stream in probe.subtitle_streams), None)
                album_art_stream = next((stream for stream in probe.album_art_streams), None)
                early_result = _validate_streams(args, path, video_stream, audio_stream)

        if early_result is _PROCESS_CONTINUE:
            output_path = output_path.with_suffix(_output_suffix(video_stream, audio_stream))
            path, output_path = devices.clobber(args, path, output_path)
            if path is None:
                early_result = output_path
            else:
                path = Path(path)
                output_path = Path(output_path)

    return (
        early_result,
        path,
        output_path,
        original_stats,
        probe,
        video_stream,
        audio_stream,
        subtitle_stream,
        album_art_stream,
    )


def process_path(args, path, include_timecode=False, **kwargs) -> str | list[str] | None:
    if kwargs:
        args = args_override(args, kwargs)
    output_path = web.gen_output_path(args, path, target_extension=".XXXXXXX")
    if args.simulate:
        print("ffmpeg", path, output_path)
        return str(path)

    (
        early_result,
        path,
        output_path,
        original_stats,
        probe,
        video_stream,
        audio_stream,
        subtitle_stream,
        album_art_stream,
    ) = _prepare_process_input(args, path, output_path)
    if early_result is not _PROCESS_CONTINUE:
        return early_result

    ff_opts, is_split, segment_count, output_path, option_result = _build_ffmpeg_options(
        args, path, probe, output_path, video_stream, audio_stream, subtitle_stream, album_art_stream, include_timecode
    )
    if option_result is not None:
        return option_result

    output_path.parent.mkdir(exist_ok=True, parents=True)
    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)
    command = [
        "ffmpeg",
        "-nostdin",
        *( ["-v", "9", "-loglevel", "99"] if args.verbose > consts.LOG_DEBUG_SQL else ["-hide_banner", "-loglevel", "warning"] ),
        "-y", "-i", str(path), "-movflags", "use_metadata_tags", *ff_opts,
        "-map_metadata", "0", "-map_chapters", "0", "-dn", "-max_interleave_delta", "0", str(output_path),
    ]
    output_paths = segment_paths(output_path, segment_count)
    if args.simulate:
        print(shlex.join(command))
        return str(path)
    command_result = _run_ffmpeg(args, command, output_paths)
    if command_result is False:
        output_result = str(path)
    else:
        is_file_error = command_result is True
        output_result = _validate_output_paths(path, output_paths, is_split)
    if output_result is not _PROCESS_CONTINUE:
        return output_result
    return _finalize_transcode(args, path, probe, video_stream, output_paths, original_stats, is_split, is_file_error)

def process_ffmpeg(defaults_override=None):
    args = parse_args(defaults_override)

    for raw_path in gen_paths(args, consts.AUDIO_ONLY_EXTENSIONS | consts.VIDEO_EXTENSIONS):
        path = raw_path
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise


def process_audio():
    process_ffmpeg({"audio_only": True})
