import argparse, os, shlex, subprocess
from pathlib import Path

from xklb import usage
from xklb.mediafiles import process_image
from xklb.utils import arggroups, argparse_utils, nums, path_utils, processes, web
from xklb.utils.arg_utils import gen_paths, kwargs_overwrite
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library process-ffmpeg", usage=usage.process_ffmpeg)
    arggroups.simulate(parser)
    arggroups.process_ffmpeg(parser)
    arggroups.debug(parser)

    arggroups.paths_or_stdin(parser)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.process_ffmpeg_post(args)

    return args


def is_animation_from_probe(probe) -> bool:
    if probe.audio_streams:
        return True
    for stream in probe.video_streams:
        frames = nums.safe_int(stream["nb_frames"])
        if frames is None:
            r = processes.cmd(
                "ffprobe",
                "-nostdin",
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
            if frames is None:
                raise RuntimeError

        if frames > 1:
            return True

    return False


def process_path(args, path, **kwargs):
    if kwargs:
        args = kwargs_overwrite(args, kwargs)

    output_path = Path(web.url_to_local_path(path) if str(path).startswith("http") else path)
    output_path = Path(path_utils.clean_path(bytes(output_path), max_name_len=251))

    path = Path(path)
    original_stats = path.stat()
    probe = processes.FFProbe(path)

    if not probe.streams:
        log.error("No media streams found: %s", path)
        return path

    if path.suffix.lower() in (".gif", ".png", ".apng", ".webp", ".avif", ".avifs", ".flif", ".mng"):
        is_animation = is_animation_from_probe(probe)
        if not is_animation:
            return process_image.process_path(args, path)

    video_stream = next((s for s in probe.video_streams), None)
    audio_stream = next((s for s in probe.audio_streams), None)
    if not video_stream:
        log.warning("No video stream found: %s", path)
        if args.delete_no_video:
            path.unlink()
            return None
    if not audio_stream:
        log.warning("No audio stream found: %s", path)
        if args.delete_no_audio:
            path.unlink()
            return None

    if video_stream and not args.audio_only:
        output_suffix = ".av1.mkv"
    elif not video_stream and not audio_stream:
        output_suffix = ".mkv"
    else:
        output_suffix = ".mka"
    output_path = output_path.with_suffix(output_suffix)

    if path == output_path:
        log.error("Input and output files have the same names %s", path)
        return path

    ff_opts: list[str] = []

    if video_stream:
        ff_opts.extend(["-c:v", "libsvtav1", "-preset", "8", "-crf", "44"])

        width = int(video_stream.get("width"))
        height = int(video_stream.get("height"))

        if width > (args.max_width * (1 + args.max_width_buffer)):
            ff_opts.extend(["-vf", f"scale={args.max_width}:-2"])
        elif height > (args.max_height * (1 + args.max_height_buffer)):
            ff_opts.extend(["-vf", f"scale=-2:{args.max_height}"])

    is_split = bool(audio_stream)
    if audio_stream:
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
                ff_opts.extend(["-b:a", "64k", "-frame_duration", "40"])

            if source_rate >= 44100:
                opus_rate = 48000
            elif source_rate >= 22050:
                opus_rate = 24000
            else:
                opus_rate = 16000
            ff_opts.extend(["-c:a", "libopus", "-ar", str(opus_rate), "-filter:a", "loudnorm=i=-18:tp=-3:lra=17"])

        if is_split:
            try:
                result = subprocess.check_output(
                    [
                        "ffmpeg",
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
                log.exception("Splits could not be identified. Likely broken file: %s", path)
                if args.delete_unplayable:
                    path.unlink()
                    return None
                raise

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

    if path.parent != output_path.parent:
        log.warning("Output folder will be different due to path cleaning: %s", output_path.parent)
        output_path.parent.mkdir(exist_ok=True, parents=True)

    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-i",
        str(path),
        *ff_opts,
        str(output_path),
    ]

    if args.simulate:
        print(shlex.join(command))
        return path
    else:
        try:
            processes.cmd(*command)
        except subprocess.CalledProcessError:
            log.exception("Could not transcode: %s", path)
            if args.delete_unplayable:
                path.unlink()
                return None
            else:
                raise

        if is_split:
            output_path = output_path.with_name(
                output_path.name.replace(".%03d", ".000")
            )  # TODO: support / return multiple paths...

        if not Path(output_path).exists() or output_path.stat().st_size == 0:
            output_path.unlink()  # Remove transcode
            return path

        delete_original = True
        delete_transcode = False

        if video_stream and args.audio_only and not args.no_preserve_video:
            delete_original = False

        if output_path.stat().st_size > path.stat().st_size:
            delete_original = False
            delete_transcode = True

        if delete_transcode:
            output_path.unlink()
            return path
        elif delete_original:
            path.unlink()

        os.utime(output_path, (original_stats.st_atime, original_stats.st_mtime))

    return output_path


def process_ffmpeg():
    args = parse_args()

    for path in gen_paths(args):
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_ffmpeg()
