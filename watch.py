import argparse
from pathlib import Path
from shlex import quote
from rich import inspect, print
from rich.prompt import Confirm
from db import singleColumnToList, sqlite_con
from utils import cmd
import os

parser = argparse.ArgumentParser()
parser.add_argument("db")
parser.add_argument("-keep", "--keep", action="store_true")
parser.add_argument("-f", "--force-order", action="store_true")
parser.add_argument("-s", "--search")
args = parser.parse_args()
con = sqlite_con(args.db)

next_video = dict(
    con.execute(
        f"""
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
{"and filename like '%" +args.search+ "%'" if args.search else ''}
ORDER BY seconds_per_byte ASC
limit 1
"""
    ).fetchone()
)["filename"]


def get_ordinal_video(filename):
    commonprefix = []
    testname = filename
    while len(commonprefix) < 2:
        if testname == "":
            commonprefix = [filename, filename]

        testname = testname.rsplit(" ", 1)[0]
        print("Trying", testname)
        commonprefix = singleColumnToList(
            con.execute(
                f"""
    SELECT filename
    FROM videos
    WHERE duration IS NOT NULL
    and size is not null
    and filename like '{testname}%'
    ORDER BY filename
    limit 2
    """,
            ).fetchall(),
            "filename",
        )
        print("Found", commonprefix)

    return commonprefix[0]


if args.force_order:
    next_video = get_ordinal_video(next_video)


print(next_video)

if os.path.exists(next_video) and "/keep/" not in next_video:
    cmd(f"mpv --quiet {quote(next_video)} --fs")
    if args.keep and Confirm.ask("Keep?", default=False):
        keep_path = str(Path(next_video).parent / "keep/")
        cmd(f"mkdir -p {keep_path} && mv {quote(next_video)} {quote(keep_path)}")
    else:
        cmd(f"trash-put {quote(next_video)}")

con.execute("delete from videos where filename = ?", (next_video,))
con.commit()
