import json
import os
import textwrap
from pathlib import Path
from shlex import quote

import pandas as pd
import polars as pl
import sqlite_utils
from rich import inspect
from rich.prompt import Confirm
from tabulate import tabulate

from db import sqlite_con
from utils import (
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
    mpv_options = "--fs --force-window=yes --terminal=no --speed=1"
    vlc = "vlc"
    quoted_video_path = quote(str(video_path))
    is_WSL = cmd('grep -qEi "(Microsoft|WSL)" /proc/version', strict=False).returncode == 0
    if is_WSL:
        mpv = "PULSE_SERVER=tcp:localhost mpv"
        vlc = "PULSE_SERVER=tcp:localhost cvlc"

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

        if "Heartbeat timeout, resetting connection" in watched.stderr:
            raise Exception("Media is possibly partially unwatched")

        if watched.stderr == "":
            raise Exception("catt does not exit nonzero? but something might have gone wrong")

        return  # end of chromecast

    cmd(f"{mpv} {mpv_options} {quoted_video_path}")


def main(args):
    con = sqlite_con(args.db)

    bindings = []
    filename_include_sql = ''
    filename_exclude_sql = ''
    if args.search:
        for inc in args.search.split(","):
            filename_include_sql += " AND filename LIKE ? "
            bindings.append("%" + inc.replace(" ", "%") + "%")
    if args.exclude:
        for exc in args.exclude.split(","):
            filename_exclude_sql += " AND filename NOT LIKE ? "
            bindings.append("%" + exc.replace(" ", "%") + "%")

    sql_filter = conditional_filter(args)

    LIMIT = "LIMIT " + str(args.limit)
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""
    SELECT filename, duration/60/60 as hours, duration / size AS seconds_per_byte,
    CASE
        WHEN size < 1024 THEN size || 'B'
        WHEN size >=  1024 AND size < (1024 * 1024) THEN (size / 1024) || 'KB'
        WHEN size >= (1024 * 1024)  AND size < (1024 * 1024 * 1024) THEN (size / (1024 * 1024)) || 'MB'
        WHEN size >= (1024 * 1024 * 1024) AND size < (1024 * 1024 * 1024 *1024) THEN (size / (1024 * 1024 * 1024)) || 'GB'
        WHEN size >= (1024 * 1024 * 1024 * 1024) THEN (size / (1024 * 1024 * 1024 * 1024)) || 'TB'
    END AS size
    FROM media
    WHERE 1=1
    {filename_include_sql}
    {filename_exclude_sql}
    and {sql_filter}
    ORDER BY
            {args.sort + ',' if args.sort else ''}
            {'round(seconds_per_byte,7) ASC,filename,' if args.play_in_order == 1 else ''}
            {'filename,' if args.search and ((args.play_in_order > 0) or args.print) else ''}
            seconds_per_byte ASC
    {LIMIT} {OFFSET}
    ; """

    if args.printquery:
        print_query(bindings, query)
        if args.play_in_order > 1:
            get_ordinal_media(con, args, Path('vid'), sql_filter)
        stop()

    if args.chromecast:
        args.cc_ip = get_ip_of_chromecast(args.device_name)

    if args.print:
        videos = pd.DataFrame([dict(r) for r in con.execute(query, bindings).fetchall()])

        if args.filename:
            csvf = videos[["filename"]].to_csv(index=False, header=False)
            print(csvf.strip())
        else:
            table_content = videos
            table_content[['filename']] = table_content[['filename']].applymap(
                lambda x: textwrap.fill(x, os.get_terminal_size().columns - 30)
            )
            print(
                tabulate(
                    table_content[["filename", "size", "hours"]],
                    tablefmt="fancy_grid",
                    headers="keys",
                    showindex=False,
                )
            )
            summary = videos.sum(numeric_only=True)
            print("Total hours", summary.hours)

        stop()

    if args.move:
        Path(args.move).mkdir(exist_ok=True, parents=True)
        keep_path = str(Path(args.move).resolve())

        videos = pl.DataFrame([dict(r) for r in con.execute(query, bindings).fetchall()])
        for video in videos.select("filename").to_series():
            if Path(video).exists() and "/keep/" not in video:
                quoted_next_video = quote(str(video))
                print(quoted_next_video)
                cmd(f"mv {quoted_next_video} {quote(keep_path)}")

            remove_media(con, video)
        stop()

    next_video = dict(con.execute(query, bindings).fetchone())["filename"]
    if args.play_in_order > 1:
        next_video = get_ordinal_media(con, args, Path(next_video), sql_filter)

    next_video = Path(args.prefix + next_video)
    print(next_video)

    original_video = next_video
    if next_video.exists() and "/keep/" not in str(next_video):
        quoted_next_video = quote(str(next_video))

        if args.only_video:
            has_video = (
                cmd(f'ffprobe -show_streams -select_streams v -loglevel error -i {quoted_next_video} | wc -l').stdout
                > '0'
            )
            if not has_video:
                remove_media(con, original_video)
                exit()

        if args.time_limit:
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

        if args.keep and Confirm.ask("Keep?", default=False):
            keep_path = str(Path(next_video).parent / "keep/")
            cmd(f"mkdir -p {keep_path} && mv {quoted_next_video} {quote(keep_path)}")
        else:
            cmd(f"trash-put {quoted_next_video}")

    remove_media(con, original_video)


if __name__ == "__main__":
    args = parse_args(default_chromecast="Living Room TV")

    main(args)
