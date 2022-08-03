import csv
import json
import math
import os
import re
import textwrap
from datetime import timedelta
from pathlib import Path
from shlex import quote
from shutil import which

import humanize
import pandas as pd
import sqlite_utils
from rich import inspect
from rich.prompt import Confirm
from tabulate import tabulate

from .db import sqlite_con
from .utils import (
    cmd,
    conditional_filter,
    get_ip_of_chromecast,
    get_ordinal_media,
    log,
    parse_args,
    print_query,
    remove_media,
    stop,
)


def play_mpv(args, video_path: Path):
    mpv = "mpv"
    mpv_options = ["--fs", "--force-window=yes", "--terminal=no"]
    vlc = "vlc"
    quoted_video_path = quote(str(video_path))
    # is_WSL = cmd('grep -qEi "(Microsoft|WSL)" /proc/version', strict=False).returncode == 0
    # if is_WSL:
    #     mpv = "PULSE_SERVER=tcp:localhost mpv"
    #     vlc = "PULSE_SERVER=tcp:localhost cvlc"

    if args.chromecast:
        subs = json.loads(
            cmd(f"ffprobe -loglevel error -select_streams s -show_entries stream -of json {quoted_video_path}").stdout
        )["streams"]

        subtitles_file = None
        if len(subs) > 0:
            db = sqlite_utils.Database(memory=True)
            db["subs"].insert_all(subs, pk="index")  # type: ignore
            subtitle_index = db.execute_returning_dicts(
                """select "index" from subs
                order by
                    lower(tags) like "%eng%" desc
                    , lower(tags) like "%dialog%" desc
                limit 1"""
            )[0]["index"]
            log.debug(f"Using subtitle {subtitle_index}")

            subtitles_file = cmd("mktemp --suffix=.vtt --dry-run").stdout.strip()
            cmd(
                f'ffmpeg -loglevel warning -txt_format text -i {quoted_video_path} -map "0:{subtitle_index}" "{subtitles_file}"'
            )

        if args.vlc:
            watched = cmd(
                f"{vlc} --sout '#chromecast' --sout-chromecast-ip={args.cc_ip} --demux-filter=demux_chromecast {'--sub-file='+subtitles_file if subtitles_file else ''} {quoted_video_path}"
            )
        else:
            watched = cmd(
                f"catt -d '{args.chromecast_device}' cast {quoted_video_path} {'--subtitles '+subtitles_file if subtitles_file else ''}"
            )

        if subtitles_file:
            Path(subtitles_file).unlink(missing_ok=True)

        if "Heartbeat timeout, resetting connection" in watched.stderr:
            raise Exception("Media is possibly partially unwatched")

        if watched.stderr == "":
            raise Exception("catt does not exit nonzero? but something might have gone wrong")

        return  # end of chromecast

    if which('mpv') is not None:
        has_sub = (
            cmd(
                f"</dev/null ffmpeg -c copy -map 0:s:0 -frames:s 1 -f null - -v 0 -i {quoted_video_path}",
                strict=False,
                quiet=True,
            ).returncode
            == 0
        )
        if not has_sub:
            mpv_options.append("--speed=1.7")
        else:
            mpv_options.append("--speed=1")

        cmd('mpv', *mpv_options, quoted_video_path)
    else:
        cmd('xdg-open', quoted_video_path)


def keep_video(video: Path):
    kp = re.match(".*?/mnt/d/(.*?)/", str(video))
    if kp:
        keep_path = str(Path(kp[0], "keep/"))
    else:
        keep_path = str(video.parent / "keep/")
    cmd(f"mkdir -p {keep_path} && mv {quote(str(video))} {quote(keep_path)}")


def watch(args):
    con = sqlite_con(args.db)

    bindings = []
    filename_include_sql = ""
    filename_exclude_sql = ""
    if args.search:
        for inc in args.search.split(","):
            filename_include_sql += " AND filename LIKE ? "
            bindings.append("%" + inc.replace(" ", "%").replace("%%", " ") + "%")
    if args.exclude:
        for exc in args.exclude.split(","):
            filename_exclude_sql += " AND filename NOT LIKE ? "
            bindings.append("%" + exc.replace(" ", "%").replace("%%", " ") + "%")

    sql_filter = conditional_filter(args)

    LIMIT = "LIMIT " + str(args.limit)
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""
    SELECT filename, duration/60/60 as hours, duration / size AS seconds_per_byte, size
    FROM media
    WHERE 1=1
    {filename_include_sql}
    {filename_exclude_sql}
    and {sql_filter}
    ORDER BY
            {args.sort + ',' if args.sort else ''}
            {'filename,' if args.print or args.search or args.play_in_order > 0 else ''}
            seconds_per_byte ASC
    {LIMIT} {OFFSET}
    """

    if 'a' in args.print:
        query = f"""select
            "Aggregate" as filename
            , sum(hours) hours
            , avg(seconds_per_byte) seconds_per_byte
            , sum(size) size
        from ({query})
        """

    if 'q' in args.print:
        print_query(bindings, query)
        if args.play_in_order > 1:
            get_ordinal_media(con, args, Path("vid"), sql_filter)
        stop()

    if args.chromecast:
        args.cc_ip = get_ip_of_chromecast(args.device_name)

    if args.print:
        videos = pd.DataFrame([dict(r) for r in con.execute(query, bindings).fetchall()])

        if 'f' in args.print:
            if args.limit == 1:
                f = videos[["filename"]].loc[0].iat[0]
                if not Path(f).exists():
                    remove_media(con, f)
                    return main()
                print(f)
            else:
                csvf = videos[["filename"]].to_csv(index=False, header=False, sep = '\t', quoting=csv.QUOTE_NONE)
                print(csvf.strip())
        else:
            table_content = videos
            table_content[["filename"]] = table_content[["filename"]].applymap(
                lambda x: textwrap.fill(x, os.get_terminal_size().columns - 30)
            )
            table_content[["size"]] = table_content[["size"]].applymap(lambda x: humanize.naturalsize(x))
            print(
                tabulate(
                    table_content[["filename", "size", "hours"]],
                    tablefmt="fancy_grid",
                    headers="keys",
                    showindex=False,
                )
            )
            summary = videos.sum(numeric_only=True)
            duration = timedelta(hours=int(summary.hours), minutes=math.ceil(summary.hours % 1 * 60))
            print("Total duration:", humanize.precisedelta(duration, minimum_unit='minutes'))

        stop()

    if args.move:
        Path(args.move).mkdir(exist_ok=True, parents=True)
        keep_path = str(Path(args.move).resolve())

        videos = pd.DataFrame([dict(r) for r in con.execute(query, bindings).fetchall()])
        for video in videos[["filename"]]:
            if Path(video).exists() and "/keep/" not in video:
                quoted_next_video = quote(str(video))
                print(quoted_next_video)
                cmd(f"mv {quoted_next_video} {quote(keep_path)}")

            remove_media(con, video)
        stop()

    next_video = dict(con.execute(query, bindings).fetchone())["filename"]
    if args.play_in_order > 1:
        next_video = get_ordinal_media(con, args, Path(next_video), sql_filter)

    original_video = Path(next_video)
    next_video = Path(args.prefix + next_video)
    print(next_video)

    if "/keep/" in str(next_video):
        keep_video(next_video)
        remove_media(con, original_video)
        exit()

    if next_video.exists():
        quoted_next_video = quote(str(next_video))

        if args.only_video:
            has_video = (
                cmd(
                    f"ffprobe -show_streams -select_streams v -loglevel error -i {quoted_next_video} | wc -l",
                    quiet=True,
                ).stdout
                > "0"
            )
            if not has_video:
                remove_media(con, original_video)
                exit()

        if args.time_limit:  # TODO: replace with timer...
            seconds = args.time_limit * 60
            gap_time = 14
            temp_next_video = cmd(f"mktemp --suffix={next_video.suffix} --dry-run").stdout.strip()
            temp_video = cmd(f"mktemp --suffix={next_video.suffix} --dry-run").stdout.strip()

            # clip x mins of target video file into new temp video file for playback
            cmd(f"ffmpeg -i {quoted_next_video} -ss 0 -t {seconds} -c copy {temp_next_video}")
            # replace video file to prevent re-watching
            cmd(f"mv {quoted_next_video} {temp_video}")
            cmd(f"ffmpeg -i {temp_video} -ss {seconds - gap_time} -c copy {quoted_next_video} && rm {temp_video}")

            next_video = Path(temp_next_video)
            print(next_video)

        if args.force_transcode:
            temp_video = cmd(f"mktemp --suffix=.mkv --dry-run").stdout.strip()
            cmd(f"mv {quoted_next_video} {temp_video}")
            next_video = next_video.with_suffix(".mkv")
            cmd(
                (
                    f"ffmpeg -loglevel error -stats -i {temp_video} -map 0 -scodec webvtt -vcodec h264"
                    " -preset fast -profile:v high -level 4.1 -crf 17 -pix_fmt yuv420p"
                    " -acodec opus -ac 2 -b:a 128k -filter:a loudnorm=i=-18:lra=17"
                    f" {quoted_next_video} && rm {temp_video}"
                )
            )
            print(next_video)

        play_mpv(args, next_video)

        if args.action == 'keep':
            keep_video(next_video)
        elif args.action == 'ask' and Confirm.ask("Keep?", default=False):
            keep_video(next_video)
        else:
            if len(args.prefix) > 0:
                cmd(f"/bin/rm {quoted_next_video}")
            else:
                cmd(f"trash-put {quoted_next_video}")

    remove_media(con, original_video)


def main():
    args = parse_args(default_chromecast="Living Room TV")

    watch(args)


if __name__ == "__main__":
    main()
