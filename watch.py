import argparse
import os
import re
from pathlib import Path
from shlex import quote
from rich import inspect, print
from rich.prompt import Confirm
from db import singleColumnToList, sqlite_con
from utils import cmd


def get_ordinal_video(con, filename):
    similar_videos = []
    testname = filename
    while len(similar_videos) < 2:
        remove_groups = re.split(r"([\W_]+)", testname)
        remove_chars = ""
        remove_chars_i = 1
        while len(remove_chars) < 1:
            remove_chars += remove_groups[-remove_chars_i]
            remove_chars_i += 1

        newtestname = testname[: -len(remove_chars)]
        print("Trying", newtestname)

        if testname == "" or newtestname == testname:
            return filename

        testname = newtestname
        similar_videos = singleColumnToList(
            con.execute(
                """SELECT filename FROM videos
            WHERE duration IS NOT NULL
                and size is not null
                and filename like ?
            ORDER BY filename
            limit 2
            """,
                (testname + "%",),
            ).fetchall(),
            "filename",
        )
        print("Found", similar_videos)

        commonprefix = os.path.commonprefix(similar_videos)
        if len(Path(commonprefix).name) < 5:
            return filename

    return similar_videos[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    parser.add_argument("-keep", "--keep", action="store_true")
    parser.add_argument("-s", "--search")
    parser.add_argument("-S", "--skip")
    parser.add_argument("-O", "--play-in-order", action="store_true")
    parser.add_argument("-r", "--random", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
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
    {"and filename like %(search)s" if args.search else ''}
    ORDER BY {'random(),' if args.random else ''} seconds_per_byte ASC
    limit 1 OFFSET {args.skip if args.skip else 0}
    """,
            dict(search="%" + (args.search or "") + "%"),
        ).fetchone()
    )["filename"]

    if args.play_in_order:
        next_video = get_ordinal_video(con, next_video)

    print(next_video)

    if os.path.exists(next_video) and "/keep/" not in next_video:
        cmd(f"mpv {quote(next_video)} --fs --force-window=yes --terminal=no")
        if args.keep and Confirm.ask("Keep?", default=False):
            keep_path = str(Path(next_video).parent / "keep/")
            cmd(f"mkdir -p {keep_path} && mv {quote(next_video)} {quote(keep_path)}")
        else:
            cmd(f"trash-put {quote(next_video)}")

    con.execute("delete from videos where filename = ?", (next_video,))
    con.commit()


if __name__ == "__main__":
    main()
