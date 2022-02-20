import argparse
import os
import re
from pathlib import Path
from shlex import quote

from rich import inspect, print
from rich.prompt import Confirm

from db import singleColumnToList, sqlite_con
from utils import cmd, log


def get_ordinal_video(con, args, filename: Path):
    similar_videos = []
    testname = str(filename)
    while len(similar_videos) < 2:
        remove_groups = re.split(r"([\W_]+)", testname)
        remove_chars = ""
        remove_chars_i = 1
        while len(remove_chars) < 1:
            remove_chars += remove_groups[-remove_chars_i]
            remove_chars_i += 1

        newtestname = testname[: -len(remove_chars)]
        print(f"Matches for '{newtestname}':")

        if testname == "" or newtestname == testname:
            return filename

        testname = newtestname
        similar_videos = singleColumnToList(
            con.execute(
                f"""SELECT filename FROM videos
            WHERE {args.sql_filter}
                and filename like ?
            ORDER BY filename
            limit 2
            """,
                ("%" + testname + "%",),
            ).fetchall(),
            "filename",
        )
        print(similar_videos)

        commonprefix = os.path.commonprefix(similar_videos)
        if len(Path(commonprefix).name) < 5:
            return filename

        if args.last:
            return similar_videos[0]

    return similar_videos[0]


def play_mpv(video_path: Path):
    mpv_options = "--fs --force-window=yes --terminal=no"
    quoted_next_video = quote(str(video_path))

    is_WSL = cmd('grep -qEi "(Microsoft|WSL)" /proc/version',strict=False).returncode == 0
    if is_WSL:
        windows_path = cmd(f"wslpath -w {quoted_next_video}").stdout.strip()
        return f'mpv.exe {mpv_options} "{windows_path}"'

    return f"mpv {mpv_options} {quoted_next_video}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    parser.add_argument("-keep", "--keep", action="store_true")
    parser.add_argument("-s", "--search")
    parser.add_argument("-S", "--skip")
    parser.add_argument("-d", "--duration", type=int)
    parser.add_argument("-dm", "--min-duration", type=int)
    parser.add_argument("-dM", "--max-duration", type=int)
    parser.add_argument("-sz", "--size", type=int)
    parser.add_argument("-szm", "--min-size", type=int)
    parser.add_argument("-szM", "--max-size", type=int)
    parser.add_argument("-mv", "--move")
    parser.add_argument("-1", "--last", action="store_true")
    parser.add_argument("-O", "--play-in-order", action="store_true")
    parser.add_argument("-r", "--random", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    con = sqlite_con(args.db)

    bindings = []
    if args.search:
        bindings.append("%" + args.search + "%")

    args.sql_filter = f"""duration IS NOT NULL and size IS NOT NULL
    {f'and duration >= {args.min_duration}' if args.min_duration else ''}
    {f'and {args.max_duration} >= duration' if args.max_duration else ''}
    {f'and {args.duration + (args.duration /10)} >= duration and duration >= {args.duration - (args.duration /10)}' if args.duration else ''}

    {f'and size >= {args.min_size}' if args.min_size else ''}
    {f'and {args.max_size} >= size' if args.max_size else ''}
    {f'and {args.size + (args.size /10)} >= size and size >= {args.size - (args.size /10)}' if args.size else ''}
    """

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
    WHERE {args.sql_filter}
    {"and filename like ?" if args.search else ''}
    ORDER BY {'random(),' if args.random else ''} seconds_per_byte ASC
    limit 1 OFFSET {args.skip if args.skip else 0}
    """,
            bindings,
        ).fetchone()
    )["filename"]

    next_video = Path(next_video)
    if args.play_in_order:
        next_video = Path(get_ordinal_video(con, args, next_video))

    print(next_video)

    if next_video.exists() and "/keep/" not in str(next_video):
        quoted_next_video = quote(str(next_video))

        if args.move:
            keep_path = str(Path(args.move))
            cmd(f"mv {quoted_next_video} {quote(keep_path)}")
        else:
            cmd(play_mpv(next_video))

            if args.keep and Confirm.ask("Keep?", default=False):
                keep_path = str(Path(next_video).parent / "keep/")
                cmd(f"mkdir -p {keep_path} && mv {quoted_next_video} {quote(keep_path)}")
            else:
                cmd(f"trash-put {quoted_next_video}")

    con.execute("delete from videos where filename = ?", (str(next_video),))
    con.commit()


if __name__ == "__main__":
    main()
