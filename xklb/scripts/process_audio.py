import argparse, json, shlex, subprocess
from pathlib import Path

from xklb import usage
from xklb.utils import nums, objects, web
from xklb.utils.log_utils import log

DEFAULT_MIN_SPLIT = "20s"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library process-audio", usage=usage.process_audio)
    parser.add_argument("--always-split", action="store_true")
    parser.add_argument("--split-longer-than")
    parser.add_argument("--min-split-segment", default=DEFAULT_MIN_SPLIT)
    parser.add_argument("--delete-video", action="store_true")
    parser.add_argument("--delete-unplayable", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    args.split_longer_than = nums.human_to_seconds(args.split_longer_than)
    args.min_split_segment = nums.human_to_seconds(args.min_split_segment)

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def process_path(
    path,
    always_split=False,
    split_longer_than=None,
    min_split_segment=nums.human_to_seconds(DEFAULT_MIN_SPLIT),
    dry_run=False,
    delete_broken=False,
    delete_video=False,
):
    if path.startswith("http"):
        output_path = Path(web.url_to_local_path(path)).with_suffix(".mka")
    else:
        output_path = Path(path).with_suffix(".mka")

    path = Path(path)
    ffprobe_cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
    result = subprocess.run(ffprobe_cmd, capture_output=True)
    info = json.loads(result.stdout)

    if "streams" not in info:
        print("No stream found:", path)
        return path
    audio_stream = next((stream for stream in info["streams"] if stream["codec_type"] == "audio"), None)
    video_stream = next((stream for stream in info["streams"] if stream["codec_type"] == "video"), None)
    if not audio_stream:
        print("No audio stream found:", path)
        return path

    channels = audio_stream.get("channels") or 2
    bitrate = int(audio_stream.get("bit_rate") or info["format"].get("bit_rate") or 256000)
    source_rate = int(audio_stream.get("sample_rate") or 44100)
    duration = float(audio_stream.get("duration") or info["format"].get("duration") or 0)

    try:
        assert bitrate > 0
        assert channels > 0
        assert source_rate > 0
    except AssertionError:
        log.exception("Broken file or audio format misdetected: %s", path)
        if delete_broken:
            path.unlink()
            return None
        return path

    ff_opts: list[str] = []
    if channels == 1:
        ff_opts.extend(["-ac 1"])
    else:
        ff_opts.extend(["-ac 2"])

    if bitrate >= 256000:
        ff_opts.extend(["-b:a 128k"])
    else:
        ff_opts.extend(["-b:a 64k", "-frame_duration 40"])

    if source_rate >= 44100:
        opus_rate = 48000
    elif source_rate >= 22050:
        opus_rate = 24000
    else:
        opus_rate = 16000
    ff_opts.extend([f"-ar {opus_rate}"])

    is_split = always_split or (split_longer_than and duration > split_longer_than)
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
            if delete_broken:
                path.unlink()
                return None
            raise

        splits = result.decode().split("\n")
        splits = [line.split("=")[1] for line in splits if "lavfi.silence_start" in line]

        prev = 0.0
        final_splits = []
        for split in splits:
            split = float(split)
            if (split - prev) >= min_split_segment:  # type: ignore
                final_splits.append(str(split))
                prev = split

        if final_splits:
            output_path = path.with_suffix(".%03d.mka")
            final_splits = ",".join(final_splits)
            print(f"Splitting {path} at points: {final_splits}")
            ff_opts.extend(["-f segment", f"-segment_times {final_splits}"])

    cmd = f'ffmpeg -nostdin -hide_banner -loglevel warning -y -i {shlex.quote(str(path))} -vn -c:a libopus {" ".join(ff_opts)} -filter:a loudnorm=i=-18:tp=-3:lra=17 {shlex.quote(str(output_path))}'
    if dry_run:
        print(cmd)
    else:
        try:
            subprocess.check_call(cmd, shell=True)
        except subprocess.CalledProcessError:
            log.exception("Could not transcode: %s", path)
            if delete_broken:
                path.unlink()
                return None
            else:
                raise

        if video_stream:
            if delete_video:
                path.unlink()  # Remove original
        elif is_split:
            path.unlink()  # Remove original
            return path.with_suffix(".000.mka")  # TODO: return multiple paths...
        else:
            if output_path.stat().st_size > path.stat().st_size:
                output_path.unlink()  # Remove transcode
                return path
            else:
                path.unlink()  # Remove original
    return output_path


def process_audio():
    args = parse_args()

    for path in args.paths:
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(
                path,
                always_split=args.always_split,
                split_longer_than=args.split_longer_than,
                min_split_segment=args.min_split_segment,
                delete_broken=args.delete_unplayable,
                delete_video=args.delete_video,
                dry_run=args.dry_run,
            )
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_audio()
