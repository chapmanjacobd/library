import argparse
import json
import os
import re
from pathlib import Path
from shlex import quote

import numpy as np
import pandas as pd
import sqlite_utils
from natsort import index_natsorted
from pychromecast import discovery
from rich import inspect, print
from rich.prompt import Confirm
from tabulate import tabulate

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
        log.debug(f"Matches for '{newtestname}':")

        if testname == "" or newtestname == testname:
            return filename

        testname = newtestname
        similar_videos = singleColumnToList(
            con.execute(
                f"""SELECT filename FROM media
            WHERE {args.sql_filter}
                and filename like ?
            ORDER BY filename
            limit 2
            """,
                ("%" + testname + "%",),
            ).fetchall(),
            "filename",
        )
        log.info(similar_videos)

        commonprefix = os.path.commonprefix(similar_videos)
        if len(Path(commonprefix).name) < 5:
            return filename

        if args.last:
            return similar_videos[0]

    return similar_videos[0]


def get_ip_of_chromecast(device_name):
    cast_infos, browser = discovery.discover_listed_chromecasts(friendly_names=[device_name])
    browser.stop_discovery()
    if len(cast_infos) == 0:
        print("Target chromecast device not found")
        exit(53)

    return cast_infos[0].host


def play_mpv(args, video_path: Path):
    mpv = "mpv"
    mpv_options = "--fs --force-window=yes --terminal=no"
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
            db["subs"].insert_all(subs, pk="index")
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    parser.add_argument("-1", "--last", action="store_true")
    parser.add_argument("-cast-to", "--chromecast-device", default="Living Room TV")
    parser.add_argument("-cast", "--chromecast", action="store_true")
    parser.add_argument("-f", "--force-transcode", action="store_true")
    parser.add_argument("-d", "--duration", type=int)
    parser.add_argument("-dM", "--max-duration", type=int)
    parser.add_argument("-dm", "--min-duration", type=int)
    parser.add_argument("-keep", "--keep", action="store_true")
    parser.add_argument("-list", "--list", action="store_true")
    parser.add_argument("-mv", "--move")
    parser.add_argument("-O", "--play-in-order", action="store_true")
    parser.add_argument("-r", "--random", action="store_true")
    parser.add_argument("-s", "--search")
    parser.add_argument("-S", "--skip")
    parser.add_argument("-t", "--time-limit", type=int)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("-vlc", "--vlc", action="store_true")
    parser.add_argument("-z", "--size", type=int)
    parser.add_argument("-zM", "--max-size", type=int)
    parser.add_argument("-zm", "--min-size", type=int)
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
    WHERE {args.sql_filter}
    {"and filename like ?" if args.search else ''}
    ORDER BY {'random(),' if args.random else ''}
            {'filename,' if args.search and args.play_in_order else ''}
            seconds_per_byte ASC
    {'' if args.list else 'LIMIT 1' + (f' OFFSET {args.skip}' if args.skip else '')}
    """

    if args.chromecast:
        args.cc_ip = get_ip_of_chromecast(args.device_name)

    if args.list:
        videos = pd.DataFrame([dict(r) for r in con.execute(query, bindings).fetchall()])
        videos["stem"] = videos.filename.apply(lambda x: Path(x).stem)
        videos.sort_values("stem", key=lambda x: np.argsort(index_natsorted(videos["stem"])), inplace=True)
        print(
            tabulate(
                # videos,
                videos[["filename", "size", "hours"]],
                tablefmt="github",
                headers="keys",
            )
        )
        exit(1)  # use nonzero code to stop shell repeat

    next_video = dict(con.execute(query, bindings).fetchone())["filename"]

    next_video = Path(next_video)
    if args.play_in_order:
        next_video = Path(get_ordinal_video(con, args, next_video))

    original_video = next_video
    print(original_video)
    if next_video.exists() and "/keep/" not in str(next_video):

        if args.time_limit:
            seconds = args.time_limit * 60
            gap_time = 14
            temp_next_video = cmd(f"mktemp --suffix={next_video.suffix} --dry-run").stdout.strip()
            temp_video = cmd(f"mktemp --suffix={next_video.suffix} --dry-run").stdout.strip()

            # clip x mins of target video file into new temp video file for playback
            cmd(f"ffmpeg -i {quote(str(next_video))} -ss 0 -t {seconds} -c copy {temp_next_video}")
            # replace video file to prevent re-watching
            cmd(f"mv {quote(str(next_video))} {temp_video}")
            cmd(f"ffmpeg -i {temp_video} -ss {seconds - gap_time} -c copy {quote(str(next_video))} && rm {temp_video}")

            next_video = Path(temp_next_video)
            print(next_video)

        if args.force_transcode:
            temp_video = cmd(f"mktemp --suffix=.mkv --dry-run").stdout.strip()
            cmd(f"mv {quote(str(next_video))} {temp_video}")
            next_video = next_video.with_suffix(".mkv")
            cmd(
                (
                    f"ffmpeg -loglevel error -stats -i {temp_video} -map 0 -scodec webvtt -vcodec h264"
                    " -preset fast -profile:v high -level 4.1 -crf 17 -pix_fmt yuv420p"
                    " -acodec opus -ac 2 -b:a 128k -filter:a loudnorm=i=-18:lra=17"
                    f" {quote(str(next_video))} && rm {temp_video}"
                )
            )
            print(next_video)

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

    con.execute("delete from media where filename = ?", (str(original_video),))
    con.commit()


if __name__ == "__main__":
    main()
