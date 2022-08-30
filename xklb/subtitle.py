import argparse, os, tempfile
from pathlib import Path
from shlex import quote
from typing import List

import ffmpeg, pysubs2
from ffmpeg import Error
from joblib import Parallel, delayed

from xklb.paths import SUB_TEMP_DIR, get_media_files, youtube_dl_id
from xklb.utils import cmd, flatten, log, remove_text_inside_brackets, remove_whitespaace

SUBTITLE_FORMATS = "vtt|srt|ssa|ass|jss|aqt|mpl2|mpsub|pjs|rt|sami|smi|stl|xml|txt|psb|ssf|usf"
IMAGE_SUBTITLE_CODECS = ["dvbsub", "dvdsub", "pgssub", "xsub", "dvb_subtitle", "dvd_subtitle", "hdmv_pgs_subtitle"]


def extract(video_file, stream_index):
    temp_srt = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)

    stream_id = "0:" + str(stream_index)

    try:
        ffmpeg.input(video_file).output(temp_srt, map=stream_id).run(quiet=True)
    except Error as e:
        log.info(
            f"Could not extract subtitle {stream_id} from video file. Likely incorrect subtitle character encoding set. %s",
            video_file,
        )
        log.debug(e.stderr.decode())
        return None

    return temp_srt


def convert_to_srt(path):
    temp_srt = tempfile.mktemp(".srt", dir=SUB_TEMP_DIR)
    try:
        ffmpeg.input(path).output(temp_srt).run(quiet=True)
    except Error as e:
        log.info("Could not convert subtitle")
        log.info(e.stderr.decode())
        raise UnicodeDecodeError("utf-8", b"Dr. John A. Zoidberg", 1, 2, "Bleh!")
    else:
        return temp_srt


def read_sub_unsafe(path):
    return [
        remove_text_inside_brackets(caption.text.replace(r"\N", " ").replace(r"\n", " ").replace("\n", " "))
        for caption in pysubs2.load(path, format_="srt")
    ]


def read_sub(path):
    if Path(path).suffix.lower() != ".srt":
        path = convert_to_srt(path)

    try:
        return read_sub_unsafe(path)
    except UnicodeDecodeError:
        return read_sub_unsafe(convert_to_srt(path))


def subs_to_text(video_path, paths: List[str]):
    def sub_to_text(path):
        try:
            return read_sub(path)
        except UnicodeDecodeError:
            log.warning(f"[{video_path}] Could not decode subtitle {path}")
            return []

    subtitles = " ".join(list(dict.fromkeys(flatten([sub_to_text(path) for path in paths]))))
    return remove_whitespaace(subtitles)


def has_internal_subtitle(file):
    internal_sub = cmd(
        f"ffmpeg -hide_banner -nostdin -i {quote(str(file))} -c copy -map 0:s:0 -frames:s 1 -f null - -v 0",
        strict=False,
        shell=True,
    ).returncode
    if internal_sub == 0:
        return True


def get_external(file):
    p = Path(file)

    subtitles = [
        str(sub_p) for sub_p in p.parent.glob(p.stem + "*") if sub_p.suffix[1:].lower() in SUBTITLE_FORMATS.split("|")
    ]

    if len(subtitles) > 0:
        return subtitles

    return []


def get(args, file):
    try:
        if has_internal_subtitle(file) or len(get_external(file)) > 0:
            return
    except Exception:
        pass

    try:
        yt_video_id = youtube_dl_id(file)
    except Exception as e:
        print(file)
        print(e)
        return

    run_subliminal = not args.youtube_only
    run_youtube = args.youtube_only  # for new videos I already have yt-dlp get the subtitle

    if run_youtube and len(yt_video_id) > 0:
        print(yt_video_id)
        cmd(
            (
                "yt-dlp --sub-lang 'en,EN,en.*,en-*,EN.*,EN-*eng,ENG,english,English,ENGLISH'"
                " --embed-subs --compat-options no-keep-subs --write-sub --write-auto-sub"
                " --no-download-archive --skip-download --limit-rate 10K"
                f" https://youtu.be/{yt_video_id}"
            ),
            cwd=str(Path(file).parent),
            strict=False,
        )

    if run_subliminal:
        print(f"[{file}] Downloading subtitles")
        cmd(
            "subliminal",
            "--opensubtitles",
            os.environ["OPEN_SUBTITLE_CREDENTIALS"],
            "download",
            "-l",
            "en",
            file,
            # strict=False
        )


def main():
    parser = argparse.ArgumentParser(prog="lb subtitle")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--youtube-only", action="store_true")
    parser.add_argument("--subliminal-only", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    video_files = get_media_files(args)

    Parallel(n_jobs=6 if args.verbose == 0 else 1)(delayed(get)(args, file) for file in video_files)


if __name__ == "__main__":
    main()
