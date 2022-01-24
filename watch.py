import argparse
from pathlib import Path
from shlex import quote
from rich import inspect, print
from rich.prompt import Confirm
from db import sqlite_con
from utils import cmd
import os

parser = argparse.ArgumentParser()
parser.add_argument("db")
parser.add_argument("-keep", "--keep", action="store_true")
args = parser.parse_args()
con = sqlite_con(args.db)

next_video = dict(
    con.execute(
        """
SELECT filename, duration / size AS seconds_per_byte,
CASE
    WHEN size < 1024 THEN size || 'B'
    WHEN size >=  1024 AND size < (1024 * 1024) THEN (size / 1024) || 'KB'
    WHEN size >= (1024 * 1024)  AND size < (1024 * 1024 * 1024) THEN (size / (1024 * 1024)) || 'MB'
    WHEN size >= (1024 * 1024 * 1024) AND size < (1024 * 1024 * 1024 *1024) THEN (size / (1024 * 1024 * 1024)) || 'GB'
    WHEN size >= (1024 * 1024 * 1024 * 1024) THEN (size / (1024 * 1024 * 1024 * 1024)) || 'TB'
END AS size
FROM videos
WHERE duration IS NOT NULL
ORDER BY 2 ASC
limit 1
"""
    ).fetchone()
)["filename"]

print(next_video)

if os.path.exists(next_video) and "/keep/" not in next_video:
    cmd(f"mpv --quiet {quote(next_video)} --fs")
    if args.keep and Confirm.ask("Keep?", default=True):
        keep_path = str(Path(next_video).parent / "keep/")
        cmd(f"mkdir -p {keep_path} && mv {quote(next_video)} {quote(keep_path)}")
    else:
        cmd(f"trash-put {quote(next_video)}")

con.execute("delete from videos where filename = ?", (next_video,))
con.commit()
