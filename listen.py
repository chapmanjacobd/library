import argparse
import json
import os
import re
from pathlib import Path
from shlex import quote

from rich import inspect, print
from rich.prompt import Confirm

from db import singleColumnToList, sqlite_con
from utils import cmd, log
import sqlite_utils

"""
function mpcatt
   for file in (fd . ~/d/80_Now_Listening/ -tf | shuf -n50)
      echo "$file" > /tmp/mpcatt_playing

      catt cast "$file" &

      grep -qEi "(Microsoft|WSL)" /proc/version
      if test $status -eq 0
          sleep 1.8 && mpv.com (wslpath -w "$file") --ontop-level=desktop --ontop=no --video=no --audio-display=no --player-operation-mode=cplayer --input-ipc-server='C:\tmp\mpv_socket'
      else
          sleep 1.6 && mpv "$file" --no-video
      end

   end
end
~ # type mp
mp is a function with definition
# Defined in /root/.config/fish/functions/mp.fish @ line 2
function mp
    if count $argv >/dev/null
        mpv --input-ipc-server=/tmp/mpv_socket --shuffle --no-video $argv
    else
        mpv --input-ipc-server=/tmp/mpv_socket --shuffle --no-video ~/Music/
    end
end
"""
# mpv.com --input-ipc-server="\\.\pipe\mpv_socket" -- "D:\80_Now_Listening\1-01_.opus"
# echo cycle volume +1  >\\.\pipe\mpv_socket
# echo cycle volume -1  >\\.\pipe\mpv_socket
# echo cycle pause >\\.\pipe\mpv_socket
# echo quit >\\.\pipe\mpv_socket

# cmd.exe /C mpv.com --input-ipc-server=\\\\.\\pipe\\mpv_socket -- "D:\80_Now_Listening\1-01_.opus"
# cmd.exe "/C echo quit >\\\\.\\pipe\\mpv_socket"


def play_mpv(args, video_path: Path):
    mpv_options = "--force-window=yes"
    quoted_next_video = quote(str(video_path))

    if args.chromecast:
        subtitles_file = cmd("mktemp --suffix=.vtt --dry-run").stdout.strip()
        cmd(
            f'ffmpeg -loglevel warning -txt_format text -i {quoted_next_video} -map "0:{subtitle_index}" "{subtitles_file}"'
        )
        cmd(f"catt -d '{args.chromecast_device}' cast {quoted_next_video} --subtitles {subtitles_file}")

        # end of chromecast

    is_WSL = cmd('grep -qEi "(Microsoft|WSL)" /proc/version', strict=False).returncode == 0
    if is_WSL:
        windows_path = cmd(f"wslpath -w {quoted_next_video}").stdout.strip()
        cmd(f'mpv.exe {mpv_options} "{windows_path}"')

    cmd(f"mpv {mpv_options} {quoted_next_video}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    parser.add_argument("-keep", "--keep", action="store_true")
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

    if next_video.exists() and "/keep/" not in str(next_video):
        quoted_next_video = quote(str(next_video))

        if args.move:
            keep_path = str(Path(args.move))
            cmd(f"mv {quoted_next_video} {quote(keep_path)}")
        else:
            play_mpv(args, next_video)

            if args.keep and Confirm.ask("Keep?", default=False):
                keep_path = str(Path(next_video).parent / "keep/")
                cmd(f"mkdir -p {keep_path} && mv {quoted_next_video} {quote(keep_path)}")
            else:
                cmd(f"trash-put {quoted_next_video}")

    con.execute("delete from media where filename = ?", (str(next_video),))
    con.commit()


if __name__ == "__main__":
    main()
