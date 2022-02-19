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
    if len(file) < 15:
        return ""
    # rename old ytdl format to new one: cargo install renamer; fd -tf . -x renamer '\-([\w\-_]{11})\.= [$1].' {}
    idregx = re.compile(r"-([\w\-_]{11})\..*$|\[([\w\-_]{11})\]\..*$", flags=re.M)
    file = str(file).strip()

    yt_ids = idregx.findall(file)
    if len(yt_ids) == 0:
        return ""

    return list(filter(None, [*yt_ids[0]]))[0]


def is_file_with_subtitle(file):
    SUBTITLE_FORMATS = "ass|idx|psb|rar|smi|srt|ssa|ssf|sub|usf|vtt"
    file = Path(file)

    external_sub = []
    for ext in SUBTITLE_FORMATS.split("|"):
        glob = False
        if len(file.stem) > 13:
            try:
                glob = any(file.parent.glob(file.stem[:-12] + "*." + ext))
            except:
                print(file)

        external_sub.append(file.with_suffix("." + ext).exists() or file.with_suffix(".en." + ext).exists() or glob)

    return any(external_sub) or (
        cmd(
            f"</dev/null ffmpeg -i {quote(str(file))} -c copy -map 0:s:0 -frames:s 1 -f null - -v 0 -hide_banner",
            strict=False,
        ).returncode
        == 0
    )


def get_subtitle(args, file):
    if is_file_with_subtitle(file):
        return

    try:
        yt_video_id = ytdl_id(file)
    except:
        print(file)
        return

    run_subliminal = not args.youtube_only
    run_youtube = not args.subliminal_only

    if run_youtube and len(yt_video_id) > 0:
        print(yt_video_id)
        cmd(
            f"yt-dlp --write-sub --write-auto-sub --sub-lang en --sub-format srt/sub/ssa/vtt/ass/best --skip-download https://youtu.be/{yt_video_id}",
            cwd=str(Path(file).parent),
            strict=False,
        )

    if run_subliminal:
        print("Downloading subtitles:", file)
        cmd(
            f"subliminal --opensubtitles {os.getenv('OPEN_SUBTITLE_CREDENTIALS')} download -l en {quote(file)}",
            # strict=False,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("-yt", "--youtube-only", action="store_true")
    parser.add_argument("-sl", "--subliminal-only", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    video_files = get_video_files(args)

    Parallel(n_jobs=6 if args.verbose == 0 else 1)(delayed(get_subtitle)(args, file) for file in video_files)


if __name__ == "__main__":
    main()
