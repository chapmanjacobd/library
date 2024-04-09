import argparse, json, shlex, subprocess
from pathlib import Path

from xklb import usage
from xklb.utils import objects, processes, web
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library process-video", usage=usage.process_video)
    parser.add_argument("--delete-no-video", action="store_true")
    parser.add_argument("--delete-no-audio", action="store_true")
    parser.add_argument("--delete-unplayable", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def process_path(
    path,
    dry_run=False,
    delete_broken=False,
    delete_no_video=False,
    delete_no_audio=False,
    max_height=960,
    max_width=1440,
    max_width_buffer=0.2,
    max_height_buffer=0.2,
):
    if path.startswith("http"):
        output_path = Path(web.url_to_local_path(path)).with_suffix(".av1.mkv")
    else:
        output_path = Path(path).with_suffix(".av1.mkv")

    path = Path(path)
    ffprobe_cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]
    result = subprocess.run(ffprobe_cmd, capture_output=True)
    info = json.loads(result.stdout)

    if "streams" not in info:
        print("No stream found:", path)
        return path
    video_stream = next((stream for stream in info["streams"] if stream["codec_type"] == "video"), None)
    audio_stream = next((stream for stream in info["streams"] if stream["codec_type"] == "audio"), None)
    if not video_stream:
        print("No video stream found:", path)
        if delete_no_video:
            path.unlink()
            return None
    if not audio_stream:
        print("No audio stream found:", path)
        if delete_no_audio:
            path.unlink()
            return None

    ff_opts: list[str] = []

    if video_stream:
        ff_opts.extend(["-c:v libsvtav1", "-preset 8 -crf 44"])

        width = int(video_stream.get("width"))
        height = int(video_stream.get("height"))

        if width > (max_width * (1 + max_width_buffer)):
            ff_opts.extend([f"-vf 'scale=-2:min(iw\\,{max_width})'"])
        elif height > (max_height * (1 + max_height_buffer)):
            ff_opts.extend([f"-vf 'scale=-2:min(ih\\,{max_height})'"])

    if audio_stream:
        channels = audio_stream.get("channels") or 2
        bitrate = int(audio_stream.get("bit_rate") or info["format"].get("bit_rate") or 256000)
        source_rate = int(audio_stream.get("sample_rate") or 44100)

        try:
            assert bitrate > 0
            assert channels > 0
            assert source_rate > 0
        except AssertionError:
            log.exception("Broken file or audio format misdetected: %s", path)
            if delete_no_audio:
                path.unlink()
                return None
        else:
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
            ff_opts.extend(["-c:a libopus", f"-ar {opus_rate}", "-filter:a loudnorm=i=-18:tp=-3:lra=17"])

    cmd = f'ffmpeg -nostdin -hide_banner -loglevel warning -y -i {shlex.quote(str(path))} {" ".join(ff_opts)} {shlex.quote(str(output_path))}'
    if dry_run:
        print(cmd)
    else:
        try:
            processes.cmd(cmd, shell=True)
        except subprocess.CalledProcessError:
            log.exception("Could not transcode: %s", path)
            if delete_broken:
                path.unlink()
                return None
            else:
                raise

        if output_path.stat().st_size > path.stat().st_size:
            output_path.unlink()  # Remove transcode
            return path
        else:
            path.unlink()  # Remove original
    return output_path


def process_video():
    args = parse_args()

    for path in args.paths:
        if not path.startswith("http"):
            path = str(Path(path).resolve())

        try:
            process_path(
                path,
                delete_broken=args.delete_unplayable,
                delete_no_video=args.delete_no_video,
                delete_no_audio=args.delete_no_audio,
                dry_run=args.dry_run,
            )
        except Exception:
            print(path)
            raise


if __name__ == "__main__":
    process_video()
