import argparse, json, shlex, subprocess
from pathlib import Path
from typing import List

from xklb import usage
from xklb.utils import nums, objects
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library process-audio", usage=usage.process_audio)
    parser.add_argument("--always-split", action="store_true")
    parser.add_argument("--split-longer-than")
    parser.add_argument("--min-split-segment", default="20s")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    args.split_longer_than = nums.human_to_seconds(args.split_longer_than)
    args.min_split_segment = nums.human_to_seconds(args.min_split_segment)

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def process_path(args, path):
    path = Path(path)
    ffprobe_cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
    result = subprocess.run(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    info = json.loads(result.stdout)

    audio_stream = next((stream for stream in info["streams"] if stream["codec_type"] == "audio"), None)
    if not audio_stream:
        print("No audio stream found:", path)
        return

    channels = audio_stream["channels"]
    bitrate = int(audio_stream.get("bit_rate", None) or info["format"]["bit_rate"])
    source_rate = int(audio_stream["sample_rate"])
    duration = float(audio_stream.get("duration", None) or info["format"]["duration"])

    assert bitrate > 0
    assert channels > 0
    assert source_rate > 0

    ff_opts: List[str] = []
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

    output_path = path.with_suffix(".opus")
    if args.always_split or (args.split_longer_than and duration > args.split_longer_than):
        splits = (
            subprocess.check_output(
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
            .decode()
            .split("\n")
        )

        splits = [line.split("=")[1] for line in splits if "lavfi.silence_start" in line]

        prev = 0.0
        final_splits = []
        for split in splits:
            split = float(split)
            if (split - prev) >= args.min_split_segment:
                final_splits.append(str(split))
                prev = split

        if final_splits:
            output_path = path.with_suffix(".%03d.opus")
            final_splits = ",".join(final_splits)
            print(f"Splitting {path} at points: {final_splits}")
            ff_opts.extend(["-f segment", f"-segment_times {final_splits}"])

    cmd = f'ffmpeg -nostdin -hide_banner -loglevel warning -y -i {shlex.quote(str(path))} -vn -c:a libopus {" ".join(ff_opts)} -vbr constrained -filter:a loudnorm=i=-18:tp=-3:lra=17 {shlex.quote(str(output_path))}'
    if args.dry_run:
        print(cmd)
    else:
        subprocess.check_call(cmd, shell=True)
        path.unlink()  # Remove original


def process_audio():
    args = parse_args()

    for path in args.paths:
        path = str(Path(path).resolve())

        try:
            process_path(args, path)
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_audio()
