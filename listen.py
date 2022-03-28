import argparse
import subprocess
from pathlib import Path
from shlex import quote
from time import sleep

from rich import inspect, print

from db import sqlite_con
from utils import cmd, conditional_filter, log


def play_mpv(args, audio_path: Path):
    mpv_options = "--input-ipc-server=/tmp/mpv_socket --no-video --replaygain=track --volume=100 --keep-open=no --term-osd-bar"
    # --no-resume-playback: I no longer use this because I now only save playback progress if the media file is longer than 7 minutes
    quoted_next_audio = quote(str(audio_path))

    if args.chromecast:
        Path("/tmp/mpcatt_playing").write_text(quoted_next_audio)

        if args.no_local:
            cmd(f"catt -d '{args.chromecast_device}' cast {quoted_next_audio}")
        else:
            cast_process = subprocess.Popen(["catt", "-d", args.chromecast_device, "cast", audio_path])
            sleep(1.174)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
            # kde-inhibit --power
            cmd(f"mpv {mpv_options} -- {quoted_next_audio}")
            cast_process.communicate()  # wait for chromecast to stop (so that I can tell any chromecast to pause)
            sleep(3.0)  # give chromecast some time to breathe

        return  # end of chromecast

    cmd(f"mpv {mpv_options} -- {quoted_next_audio}")


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

    sql_filter = conditional_filter(args)

    search_string ="""and (
        filename like ?
        OR format_name like ?
        OR format_long_name like ?
        OR album like ?
        OR albumartist like ?
        OR artist like ?
        OR comment like ?
        OR composer like ?
        OR genre like ?
        OR title like ?
        OR year like ?
        OR albumgenre like ?
        OR albumgrouping like ?
        OR mood like ?
        OR key like ?
        OR gain like ?
        OR time like ?
        OR decade like ?
        OR categories like ?
        OR city like ?
        OR country like ?
    )"""

    next_audio = dict(
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
    WHERE {sql_filter}
    {search_string if args.search else ''}
    {"" if args.search else 'and listen_count = 0'}
    ORDER BY {'random(),' if args.random else ''} seconds_per_byte ASC
    limit 1 OFFSET {args.skip if args.skip else 0}
    """,
            bindings,
        ).fetchone()
    )

    next_audio = Path(next_audio["filename"])
    print(next_audio)

    if next_audio.exists():
        quoted_next_audio = quote(str(next_audio))

        if args.move:
            keep_path = str(Path(args.move))
            cmd(f"mv {quoted_next_audio} {quote(keep_path)}")
        else:
            play_mpv(args, next_audio)

    con.execute("update media set listen_count = listen_count +1 where filename = ?", (str(next_audio),))
    con.commit()


if __name__ == "__main__":
    main()
