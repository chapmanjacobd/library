import csv
import json
import math
import os
import shutil
import subprocess
import textwrap
from datetime import timedelta
from pathlib import Path
from shlex import quote
from shutil import which
from time import sleep

import humanize
import pandas as pd
import sqlite_utils
from rich.prompt import Confirm
from tabulate import tabulate

from xk.db import sqlite_con
from xk.subtitle import is_file_with_subtitle
from xk.utils import (
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


def play(args, video_path: Path):
    if which("mpv") is not None:
        player = ["mpv", "--fs", "--force-window=yes", "--terminal=no"]
    else:
        player = ["xdg-open"]

    if args.chromecast:
        subtitles_file = externalize_subtitle(video_path)

        if args.vlc:
            watched = cmd(
                f"vlc --sout '#chromecast' --sout-chromecast-ip={args.cc_ip} --demux-filter=demux_chromecast {'--sub-file='+subtitles_file if subtitles_file else ''} {video_path}"
            )
        else:
            watched = cmd(
                f"catt -d '{args.chromecast_device}' cast {video_path} {'--subtitles '+subtitles_file if subtitles_file else ''}"
            )

        if subtitles_file:
            Path(subtitles_file).unlink(missing_ok=True)

        if "Heartbeat timeout, resetting connection" in watched.stderr:
            raise Exception("Media is possibly partially unwatched")

        if watched.stderr == "":
            raise Exception("catt does not exit nonzero? but something might have gone wrong")

        return  # end of chromecast

    if not is_file_with_subtitle(video_path):
        player.append("--speed=1.7")
    else:
        player.append("--speed=1")

    cmd(*player, '--', video_path)


def play(args, audio_path):
    if which("mpv") is not None:
        player = ["mpv", "--input-ipc-server=/tmp/mpv_socket", "--no-video", "--keep-open=no", "--term-osd-bar"]
    else:
        player = ["xdg-open"]

    try:
        print(cmd("ffprobe", "-hide_banner", "-loglevel", "info", audio_path, quiet=True).stderr)
    except:
        print(audio_path)

    if args.chromecast:
        Path("/tmp/mpcatt_playing").write_text(audio_path)

        cmd("touch /tmp/sub.srt")
        if not args.with_local:
            cmd("catt", "-d", args.chromecast_device, "cast", "-s", "/tmp/sub.srt", audio_path)
        else:
            cast_process = subprocess.Popen(
                ["catt", "-d", args.chromecast_device, "cast", "-s", "/tmp/sub.srt", audio_path], preexec_fn=os.setpgrp
            )
            sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
            cmd(*player, "--", audio_path)
            cast_process.communicate()  # wait for chromecast to stop (you can tell any chromecast to pause)
            sleep(3.0)  # give chromecast some time to breathe
    else:
        cmd(*player, "--", audio_path, quiet=True)


def externalize_subtitle(video_path):
    subs = json.loads(
        cmd(
            "ffprobe",
            "-loglevel",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream",
            "-of",
            "json",
            video_path,
        ).stdout
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
        cmd(f'ffmpeg -loglevel warning -txt_format text -i {video_path} -map "0:{subtitle_index}" "{subtitles_file}"')

    return subtitles_file


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
    {sql_filter}
    ORDER BY
            {args.sort + ',' if args.sort else ''}
            {'filename,' if args.print or args.search or args.play_in_order > 0 else ''}
            seconds_per_byte ASC
    {LIMIT} {OFFSET}
    """

    if args.chromecast:
        args.cc_ip = get_ip_of_chromecast(args.device_name)

    next_video = con.execute(query, bindings).fetchone()
    if next_video is None:
        print('No media found')
        stop()

    next_video = dict(next_video)["filename"]
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
        if args.only_video:
            has_video = (
                cmd(
                    f"ffprobe -show_streams -select_streams v -loglevel error -i {quote(str(next_video))} | wc -l",
                    quiet=True,
                    shell=True,
                ).stdout
                > "0"
            )
            if not has_video:
                remove_media(con, original_video)
                exit()

        if args.force_transcode:
            temp_video = cmd("mktemp", "--suffix=.mkv", "--dry-run").stdout.strip()
            shutil.move(next_video, temp_video)
            next_video = next_video.with_suffix(".mkv")
            cmd(
                (
                    f"ffmpeg -loglevel error -stats -i {temp_video} -map 0 -scodec webvtt -vcodec h264"
                    " -preset fast -profile:v high -level 4.1 -crf 17 -pix_fmt yuv420p"
                    " -acodec opus -ac 2 -b:a 128k -filter:a loudnorm=i=-18:lra=17"
                    f" {next_video} && rm {temp_video}"
                )
            )
            print(next_video)

        play(args, next_video)

        if args.action == "keep":
            keep_video(next_video)
        elif args.action == "ask" and Confirm.ask("Keep?", default=False):
            keep_video(next_video)
        else:
            if len(args.prefix) > 0:
                next_video.unlink()
                cmd("/bin/rm", next_video)
            else:
                cmd("trash-put", next_video)

    remove_media(con, original_video)


def listen(args):
    con = sqlite_con(args.db)

    bindings = {}
    if args.search:
        bindings["search"] = "%" + args.search.replace(" ", "%").replace("%%", " ") + "%"
    if args.exclude:
        bindings["exclude"] = "%" + args.exclude.replace(" ", "%").replace("%%", " ") + "%"

    sql_filter = conditional_filter(args)

    search_string = """and (
        filename like :search
        OR mood like :search
        OR genre like :search
        OR year like :search
        OR bpm like :search
        OR key like :search
        OR time like :search
        OR decade like :search
        OR categories like :search
        OR city like :search
        OR country like :search
        OR description like :search
        OR album like :search
        OR title like :search
        OR artist like :search
    )"""

    exclude_string = """and (
        filename not like :exclude
        OR mood not like :exclude
        OR genre not like :exclude
        OR year not like :exclude
        OR bpm not like :exclude
        OR key not like :exclude
        OR time not like :exclude
        OR decade not like :exclude
        OR categories not like :exclude
        OR city not like :exclude
        OR country not like :exclude
        OR description not like :exclude
        OR album not like :exclude
        OR title not like :exclude
        OR artist not like :exclude
    )"""

    query = f"""
    SELECT filename, duration / size AS seconds_per_byte, size
    FROM media
    WHERE 1=1
    {search_string if args.search else ''}
    {exclude_string if args.exclude else ''}
    {"" if args.search else 'and listen_count = 0'}
    {sql_filter}
    ORDER BY
        listen_count asc nulls first,
        {args.sort + ',' if args.sort else ''}
        {'filename,' if args.search and (args.play_in_order > 0) else ''}
        seconds_per_byte ASC
    limit 1 OFFSET {args.skip if args.skip else 0}
    """

    next_audio = con.execute(query, bindings).fetchone()
    if next_audio is None:
        print('No media found')
        stop()

    next_audio = Path(dict(next_audio)["filename"])

    # limit to audiobook since normal music does not get deleted so only the first track would ever be played
    if "audiobook" in str(next_audio):
        next_audio = Path(get_ordinal_media(con, args, next_audio, sql_filter))

    if not next_audio.exists():
        print("Removing orphaned metadata", next_audio)
        remove_media(con, next_audio)
    else:
        if args.move:
            keep_path = str(Path(args.move))
            cmd("mv", next_audio, keep_path)
        else:
            play(args, next_audio)
            if args.action == "delete" or "audiobook" in str(next_audio).lower():
                cmd("trash-put", next_audio, strict=False)
                remove_media(con, next_audio)

    con.execute("update media set listen_count = listen_count +1 where filename = ?", (str(next_audio),))
    con.commit()


def printer(args):
    if args.print and "a" in args.print:
        query = f"""select
            "Aggregate" as filename
            , sum(hours) hours
            , avg(seconds_per_byte) seconds_per_byte
            , sum(size) size
        from ({query})
        """

    if args.print and "q" in args.print:
        print_query(bindings, query)
        if args.play_in_order > 1:
            get_ordinal_media(con, args, Path("vid"), sql_filter)
        stop()

    videos = pd.DataFrame([dict(r) for r in con.execute(query, bindings).fetchall()])

    if "f" in args.print:
        if args.limit == 1:
            f = videos[["filename"]].loc[0].iat[0]
            if not Path(f).exists():
                remove_media(con, f)
                return main()
            print(f)
        else:
            csvf = videos[["filename"]].to_csv(index=False, header=False, sep="\t", quoting=csv.QUOTE_NONE)
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
        print("Total duration:", humanize.precisedelta(duration, minimum_unit="minutes"))

    stop()


def mover(args):
    Path(args.move).mkdir(exist_ok=True, parents=True)
    keep_path = str(Path(args.move).resolve())

    videos = pd.DataFrame([dict(r) for r in con.execute(query, bindings).fetchall()])
    for video in videos[["filename"]]:
        if Path(video).exists() and "/keep/" not in video:
            shutil.move(video, keep_path)

        remove_media(con, video)
    stop()


def process_actions(args):
    if args.move:
        print('move')
        # mover(args)

    if args.print:
        print('print')
        # printer(args)

    if args.move:
        print('move')

def wt():
    args = parse_args(default_chromecast="Living Room TV")
    process_actions(args)

    print('watch')
    # watch(args)


def lt():
    args = parse_args(default_chromecast="Xylo and Orchestra")
    process_actions(args)

    print('listen')
    # try:
    #     listen(args)
    # finally:
    #     if args.chromecast:
    #         cmd("rm /tmp/mpcatt_playing", strict=False)
