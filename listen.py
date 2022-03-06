import argparse
import subprocess
from pathlib import Path
from shlex import quote
from time import sleep

from rich import inspect, print

from db import sqlite_con
from utils import cmd, log

"""
echo 'cycle pause' | socat - /tmp/mpvsocket
echo cycle volume +1  | socat - /tmp/mpvsocket
echo cycle volume -1  | socat - /tmp/mpvsocket
echo cycle pause | socat - /tmp/mpvsocket
echo quit | socat - /tmp/mpvsocket
echo 'set speed 1.0' | socat - /tmp/mpvsocket
Alt+Ctrl+[ set speed 1.0
Alt+Ctrl+[ set speed 1.0
Alt+[ multiply speed 1/1.1
Alt+] multiply speed 1.1
"""


def play_mpv(args, video_path: Path):
    mpv_options = "--input-ipc-server=/tmp/mpv_socket --no-video"
    quoted_next_video = quote(str(video_path))

    if args.chromecast:
        Path('/tmp/mpcatt_playing').write_text(quoted_next_video)

        if args.no_local:
            cmd(f"catt -d '{args.chromecast_device}' cast {quoted_next_video}")
        else:
            subprocess.Popen(["catt", "-d",args.chromecast_device,'cast',quoted_next_video])
            sleep(1.4)
            cmd(f"mpv {mpv_options} -- {quoted_next_video}")

        return # end of chromecast

    cmd(f"mpv {mpv_options} -- {quoted_next_video}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    parser.add_argument("-N", "--no-local", action="store_true")
    parser.add_argument("-cast", "--chromecast", action="store_true")
    parser.add_argument("-cast-to", "--chromecast-device", default="Xylo and Orchestra")
    parser.add_argument("-s", "--search")
    parser.add_argument("-S", "--skip")
    parser.add_argument("-d", "--duration", type=int)
    parser.add_argument("-dm", "--min-duration", type=int)
    parser.add_argument("-dM", "--max-duration", type=int)
    parser.add_argument("-sz", "--size", type=int)
    parser.add_argument("-szm", "--min-size", type=int)
    parser.add_argument("-szM", "--max-size", type=int)
    parser.add_argument("-mv", "--move")
    parser.add_argument("-wl", "--with-local", action="store_true")
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
    FROM media
    WHERE {args.sql_filter}
    {"and filename like ?" if args.search else ''}
    ORDER BY {'random(),' if args.random else ''} seconds_per_byte ASC
    limit 1 OFFSET {args.skip if args.skip else 0}
    """,
            bindings,
        ).fetchone()
    )["filename"]

    next_video = Path(next_video)
    print(next_video)

    if next_video.exists():
        quoted_next_video = quote(str(next_video))

        if args.move:
            keep_path = str(Path(args.move))
            cmd(f"mv {quoted_next_video} {quote(keep_path)}")
        else:
            play_mpv(args, next_video)

    con.execute("delete from media where filename = ?", (str(next_video),))
    con.commit()


if __name__ == "__main__":
    main()
