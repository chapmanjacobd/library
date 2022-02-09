import argparse
import os
import re
from pathlib import Path
from shlex import quote
import pandas as pd
from dotenv import load_dotenv
from joblib import Parallel, delayed
from rich import inspect, print
from extract import get_video_files
from utils import cmd

load_dotenv(dotenv_path=Path(".") / ".env")


def is_file_from_ytdl(file):
    idregx = re.compile(r"-([\w]{11})\..*$|(\[[\w]{11}\])\..*$", flags=re.M)
    file = str(file).strip()

    return len(idregx.findall(file)) > 0


def is_file_with_subtitle(file):
    return cmd(f"ffmpeg -i {quote(file)} -c copy -map 0:s:0 -frames:s 1 -f null - -v 0 -hide_banner").returncode == 0


def get_subtitle(file):
    if is_file_from_ytdl(file):
        return

    if is_file_with_subtitle(file):
        return

    cmd(f"subliminal --opensubtitles {os.getenv('OPEN_SUBTITLE_CREDENTIALS')} download -l en {quote(file)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()

    video_files = get_video_files(args)

    Parallel(n_jobs=6)(delayed(get_subtitle)(file) for file in video_files)


if __name__ == "__main__":
    main()
