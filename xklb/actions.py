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

from xklb.db import sqlite_con
from xklb.extract import audio_exclude_string, audio_include_string
from xklb.subtitle import is_file_with_subtitle
from xklb.utils import (
    Pclose,
    cmd,
    get_ordinal_media,
    log,
    mv_to_keep_folder,
    parse_args,
    print_query,
    remove_media,
    stop,
)


class Action:
    watch = "watch"
    listen = "listen"


def has_video(next_video):
    return (
        cmd(
            f"ffprobe -show_streams -select_streams v -loglevel error -i {quote(str(next_video))} | wc -l",
            quiet=True,
            shell=True,
        ).stdout
        > "0"
    )


def transcode(next_video):
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
    return next_video


def delete_media(args, media_file):
    if len(args.prefix) > 0:
        media_file.unlink()
    else:
        cmd("trash-put", media_file, strict=False)

    remove_media(args, media_file, quiet=True)


def post_act(args, media_file):
    if args.post_action == "keep":
        if args.action == Action.listen:
            args.con.execute("update media set listen_count = listen_count +1 where filename = ?", (str(media_file),))
            args.con.commit()
    elif args.post_action == "ask":
        if Confirm.ask("Keep?", default=False):
            mv_to_keep_folder(media_file)
    elif args.post_action == "delete":
        delete_media(args, media_file)
    elif args.post_action == "delete-if-audiobook":
        if "audiobook" in str(media_file).lower():
            delete_media(args, media_file)
    else:
        raise Exception("Unknown post_action", args.post_action)


def listen_chromecast(args, media_file, player):
    Path("/tmp/mpcatt_playing").write_text(media_file)
    cmd("touch /tmp/sub.srt")
    if not args.with_local:
        catt_log = cmd("catt", "-d", args.chromecast_device, "cast", "-s", "/tmp/sub.srt", media_file)
    else:
        cast_process = subprocess.Popen(
            ["catt", "-d", args.chromecast_device, "cast", "-s", "/tmp/sub.srt", media_file], preexec_fn=os.setpgrp
        )
        sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
        cmd(*player, "--", media_file)
        catt_log = Pclose(cast_process)  # wait for chromecast to stop (you can tell any chromecast to pause)
        sleep(3.0)  # give chromecast some time to breathe

    return catt_log


def externalize_subtitle(media_file):
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
            media_file,
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
        cmd(f'ffmpeg -loglevel warning -txt_format text -i {media_file} -map "0:{subtitle_index}" "{subtitles_file}"')

    return subtitles_file


def watch_chromecast(args, media_file):
    subtitles_file = externalize_subtitle(media_file)

    if args.vlc:
        catt_log = cmd(
            f"vlc --sout '#chromecast' --sout-chromecast-ip={args.cc_ip} --demux-filter=demux_chromecast {'--sub-file='+subtitles_file if subtitles_file else ''} {media_file}"
        )
    else:
        catt_log = cmd(
            f"catt -d '{args.chromecast_device}' cast {media_file} {'--subtitles '+subtitles_file if subtitles_file else ''}"
        )

    if subtitles_file:
        Path(subtitles_file).unlink(missing_ok=True)
    return catt_log


def play(args, media: pd.DataFrame):
    for m in media.to_records(index=False):
        media_file = m["filename"]

        if args.play_in_order > 1 or (args.action == Action.listen and "audiobook" in str(media_file).lower()):
            media_file = get_ordinal_media(args, Path(media_file))

        media_file = Path(args.prefix + media_file)
        if not media_file.exists():
            remove_media(args, str(media_file))
            continue

        if which("mpv") is not None:
            player = ["mpv"]
            if args.action == Action.listen:
                player.extend(["--input-ipc-server=/tmp/mpv_socket", "--no-video", "--keep-open=no", "--term-osd-bar"])
            elif args.action == Action.watch:
                player.extend(["--fs", "--force-window=yes", "--terminal=no"])
        else:
            player = ["xdg-open"]

        if args.action == Action.watch:
            print(media_file)

            if not has_video(media_file):
                print("[watch]: skipping non-video file", media_file)
                continue

        elif args.action == Action.listen:
            print(cmd("ffprobe", "-hide_banner", "-loglevel", "info", media_file, quiet=True).stderr)

        if args.transcode:
            media_file = transcode(media_file)

        if args.chromecast:
            if args.action == Action.watch:
                catt_log = watch_chromecast(args, media_file)
            elif args.action == Action.listen:
                catt_log = listen_chromecast(args, media_file, player)

            if "Heartbeat timeout, resetting connection" in catt_log.stderr:
                raise Exception("Media is possibly partially unwatched")

            if catt_log.stderr == "":
                raise Exception("catt does not exit nonzero? but something might have gone wrong")

        else:  # end of chromecast
            if args.action == Action.watch:
                if not is_file_with_subtitle(media_file):
                    player.append("--speed=1.7")
                else:
                    player.append("--speed=1")

            cmd(*player, "--", media_file, quiet=True)

        if args.post_action:
            post_act(args, media_file)


def construct_query(args):
    cf = []

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    if args.action == Action.watch:
        bindings = []
        for inc in args.include:
            cf.append(" AND filename LIKE ? ")
            bindings.append("%" + inc.replace(" ", "%").replace("%%", " ") + "%")
        for exc in args.exclude:
            cf.append(" AND filename NOT LIKE ? ")
            bindings.append("%" + exc.replace(" ", "%").replace("%%", " ") + "%")

    if args.action == Action.listen:
        bindings = {}
        for idx, inc in enumerate(args.include):
            cf.append(audio_include_string(idx))
            bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
        for idx, exc in enumerate(args.exclude):
            cf.append(audio_exclude_string(idx))
            bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"

    args.sql_filter = " ".join(cf)

    LIMIT = "LIMIT " + str(args.limit)
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""
    SELECT filename, duration/60/60 as hours, duration / size AS seconds_per_byte, size
    FROM media
    WHERE 1=1
    {args.sql_filter}
    {'and listen_count = 0' if args.action == Action.listen and not args.include else ''}
    ORDER BY
        {'listen_count asc nulls first,' if args.action == Action.listen else ''}
        {args.sort + ',' if args.sort else ''}
        {'filename,' if args.print or args.include or args.play_in_order > 0 else ''}
        seconds_per_byte ASC
    {LIMIT} {OFFSET}
    """

    return query, bindings


def printer(args, query):
    if "a" in args.print:
        query = f"""select
            "Aggregate" as filename
            , sum(hours) hours
            , avg(seconds_per_byte) seconds_per_byte
            , sum(size) size
            , count(*) count
        from ({query}) """
    else:
        query = f"""select
            filename
            , hours
            , size
        from ({query}) """

    if args.print and "q" in args.print:
        print(query)
        stop()

    videos = pd.DataFrame([dict(r) for r in args.con.execute(query).fetchall()])

    if "f" in args.print:
        if args.limit == 1:
            f = videos[["filename"]].loc[0].iat[0]
            if not Path(f).exists():
                remove_media(args, f)
                return printer(args, query)
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
                table_content,
                tablefmt="fancy_grid",
                headers="keys",
                showindex=False,
            )
        )
        summary = videos.sum(numeric_only=True)
        duration = timedelta(hours=int(summary.hours), minutes=math.ceil(summary.hours % 1 * 60))
        print("Total duration:", humanize.precisedelta(duration, minimum_unit="minutes"))

    stop()


def mover(args, media):
    Path(args.move).mkdir(exist_ok=True, parents=True)
    keep_path = str(Path(args.move).resolve())

    for media in media[["filename"]]:
        if Path(media).exists() and "/keep/" not in media:
            shutil.move(media, keep_path)

        remove_media(args, media, quiet=True)
    stop()


def process_actions(args):
    args.con = sqlite_con(args.db)
    query, bindings = construct_query(args)

    if args.print:
        printer(args, query=print_query(query, bindings))

    media = pd.DataFrame([dict(r) for r in args.con.execute(query, bindings).fetchall()])
    if len(media) == 0:
        print("No media found")
        stop()

    if args.move:
        mover(args, media)

    play(args, media)


def wt():
    args = parse_args(default_chromecast="Living Room TV")
    args.action = Action.watch
    if not args.db:
        args.db = "video.db"

    process_actions(args)


def lt():
    args = parse_args(default_chromecast="Xylo and Orchestra")
    args.action = Action.listen
    if not args.db:
        args.db = "audio.db"

    try:
        process_actions(args)
    finally:
        if args.chromecast:
            cmd("rm /tmp/mpcatt_playing", strict=False)
