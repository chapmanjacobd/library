import argparse
import os
import re
from pathlib import Path
from shlex import quote
import pandas as pd
from dotenv import load_dotenv
from joblib import Parallel, delayed
from rich import inspect, print
from utils import cmd, get_video_files

load_dotenv(dotenv_path=Path(".") / ".env")


def ytdl_id(file) -> str:
    idregx = re.compile(r"-([\w\-_]{11})\..*$|\[([\w\-_]{11})\]\..*$", flags=re.M)
    file = str(file).strip()

    yt_ids = idregx.findall(file)
    if len(yt_ids) == 0:
        return ""

    return list(filter(None, [*yt_ids[0]]))[0]


def is_file_with_subtitle(file):
    SUBTITLE_FORMATS = "ass|idx|psb|rar|smi|srt|ssa|ssf|sub|usf|vtt"
    file = Path(file)

    external_sub_files = []
    for ext in SUBTITLE_FORMATS.split("|"):
        external_sub_files.append(
            file.with_suffix("." + ext).exists()
            or file.with_suffix(".en." + ext).exists()
            or file.parent.glob(file.stem[:-12] + "*" + ext)
        )

    return any(external_sub_files) or (
        cmd(
            f"ffmpeg -i {quote(str(file))} -c copy -map 0:s:0 -frames:s 1 -f null - -v 0 -hide_banner", strict=False
        ).returncode
        == 0
    )


def get_subtitle(args, file):
    if is_file_with_subtitle(file):
        return

    yt_video_id = ytdl_id(file)
    if args.youtube and len(yt_video_id) > 0:
        print(yt_video_id)
        cmd(
            f"yt-dlp --write-sub --write-auto-sub --sub-lang en --sub-format srt/sub/ssa/vtt/ass/best --skip-download https://youtu.be/{yt_video_id}",
            cwd=str(Path(file).resolve().parent),
            strict=False,
        )

    if not args.youtube:
        print("Downloading subtitles:", file)
        cmd(
            f"subliminal --opensubtitles {os.getenv('OPEN_SUBTITLE_CREDENTIALS')} download -l en {quote(file)}",
            # strict=False,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("-yt", "--youtube", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    video_files = get_video_files(args)

    Parallel(n_jobs=6 if args.verbose == 0 else 1)(delayed(get_subtitle)(args, file) for file in video_files)


if __name__ == "__main__":
    main()
