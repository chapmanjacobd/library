import argparse
import os
import re
from pathlib import Path
from shlex import quote

from joblib import Parallel, delayed

from xklb.utils import cmd, get_media_files


def youtube_dl_id(file) -> str:
    if len(file) < 15:
        return ""
    # rename old youtube_dl format to new one: cargo install renamer; fd -tf . -x renamer '\-([\w\-_]{11})\.= [$1].' {}
    yt_id_regex = re.compile(r"-([\w\-_]{11})\..*$|\[([\w\-_]{11})\]\..*$", flags=re.M)
    file = str(file).strip()

    yt_ids = yt_id_regex.findall(file)
    if len(yt_ids) == 0:
        return ""

    return list(filter(None, [*yt_ids[0]]))[0]


def has_internal_subtitle(file):
    internal_sub = cmd(
        f"ffmpeg -hide_banner -nostdin -i {quote(str(file))} -c copy -map 0:s:0 -frames:s 1 -f null - -v 0",
        strict=False,
        shell=True,
    ).returncode
    if internal_sub == 0:
        return True


def has_external_subtitle(file):
    SUBTITLE_FORMATS = "vtt|srt|ssa|ass|sub|idx|psb|smi|ssf|usf"
    file = Path(file)

    if any(
        [
            file.with_suffix("." + ext).exists()
            or file.with_suffix(".en." + ext).exists()
            or file.with_suffix(".eng." + ext).exists()
            for ext in SUBTITLE_FORMATS.split("|")
        ]
    ):
        return True

    if len(file.stem) <= 13:
        return False

    FORMATSUB_REGEX = re.compile(rf".*\.({SUBTITLE_FORMATS})")
    for globbed in file.parent.glob(file.stem[:-12] + r".*"):
        match = FORMATSUB_REGEX.match(str(globbed))
        if match:
            return True

    return False


def get_subtitle(args, file):
    try:
        if has_internal_subtitle(file) or has_external_subtitle(file):
            return
    except Exception:
        pass

    try:
        yt_video_id = youtube_dl_id(file)
    except Exception:
        print(file)
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
        print("Downloading subtitles:", file)
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
    parser.add_argument("-yt", "--youtube-only", action="store_true")
    parser.add_argument("-sl", "--subliminal-only", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    video_files = get_media_files(args)

    Parallel(n_jobs=6 if args.verbose == 0 else 1)(delayed(get_subtitle)(args, file) for file in video_files)


if __name__ == "__main__":
    main()
