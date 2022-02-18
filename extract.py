import argparse
import json
import os
import sys
from datetime import datetime
from shlex import quote

import pandas as pd
from joblib import Parallel, delayed
from rich import inspect, print

from db import fetchall_dict, sqlite_con
from subtitle import get_subtitle
from utils import cmd, get_video_files


def extract_metadata(file):
    try:
        ffprobe = json.loads(
            cmd(f"ffprobe -loglevel quiet -print_format json=compact=1 -show_entries format {quote(file)}").stdout
        )
    except:
        print(f"Failed reading {file}", file=sys.stderr)
        return

    if not "format" in ffprobe:
        print(f"Failed reading format {file}", file=sys.stderr)
        print(ffprobe)
        return

    stat = os.stat(file)
    blocks_allocated = stat.st_blocks * 512

    if "tags" in ffprobe["format"]:
        del ffprobe["format"]["tags"]

    if "size" in ffprobe["format"]:
        ffprobe["format"]["size"] = int(ffprobe["format"]["size"])

    if blocks_allocated == 0:
        sparseness=0
    else:
        sparseness=ffprobe["format"]["size"] / blocks_allocated

    return dict(
        **ffprobe["format"],
        # streams=ffprobe["streams"],
        sparseness=sparseness,
        time_created=datetime.fromtimestamp(stat.st_ctime),
        time_modified=datetime.fromtimestamp(stat.st_mtime),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("-ns", "--no-sub", action="store_true")
    parser.add_argument("-yt", "--youtube", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    con = sqlite_con(args.db)

    video_files = get_video_files(args)
    new_files = set(video_files)

    try:
        existing = set(map(lambda x: x["filename"], fetchall_dict(con, "select filename from videos")))
        video_files = list(new_files - existing)
    except:
        video_files = list(new_files)

    print(video_files)

    metadata = Parallel(n_jobs=-1)(delayed(extract_metadata)(file) for file in video_files) or []
    pd.DataFrame(list(filter(None, metadata))).to_sql(
        "videos",
        con=con,
        if_exists="append",
        index=False,
        chunksize=70,
        method="multi",
    )

    if not args.no_sub:
        Parallel(n_jobs=5)(delayed(get_subtitle)(args, file) for file in video_files)


if __name__ == "__main__":
    main()
