import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import textwrap
from datetime import datetime, timedelta
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
    CAST_NOW_PLAYING,
    FAKE_SUBTITLE,
    Pclose,
    Subcommand,
    cmd,
    cmd_interactive,
    get_ip_of_chromecast,
    get_ordinal_media,
    log,
    mv_to_keep_folder,
    print_query,
    remove_media,
    stop,
)


def parse_args(default_chromecast=""):
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("db", nargs="?")

    # TODO: maybe try https://dba.stackexchange.com/questions/43415/algorithm-for-finding-the-longest-prefix
    parser.add_argument("--play-in-order", "-O", action="count", default=0)

    parser.add_argument("--duration", "-d", action="append", help="Duration in minutes")

    parser.add_argument("--sort", "-u", nargs="+")
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[])
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[])
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[])

    parser.add_argument("--chromecast-device", "-cast-to", default=default_chromecast)
    parser.add_argument("--chromecast", "-cast", action="store_true")
    parser.add_argument("--with-local", "-wl", action="store_true")

    parser.add_argument("--prefix", default="", help="change root prefix; useful for sshfs")

    parser.add_argument("--size", "-z", action="append", help="Size in Megabytes")

    parser.add_argument("--print", "-p", default=False, const="p", nargs="?")
    parser.add_argument("--print-column", "-col", nargs="*")
    parser.add_argument("--limit", "-L", "-l", "-repeat", "--repeat", default=1)
    parser.add_argument("--skip", "-S", help="Offset")

    parser.add_argument("--time-limit", "-t", type=int)
    parser.add_argument("--player", "-player", nargs="*")
    parser.add_argument("--mpv-socket", default="/tmp/mpv_socket")

    parser.add_argument("--player-args-when-sub", "-player-sub", nargs="*", default=["--speed=1"])
    parser.add_argument("--player-args-when-no-sub", "-player-no-sub", nargs="*", default=["--speed=1.7"])
    parser.add_argument("--transcode", action="store_true")

    parser.add_argument("--post-action", "--action", "-k", default="keep")
    parser.add_argument("--shallow-organize", default="/mnt/d/")

    parser.add_argument("--move", "-mv")

    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--version", "-V", action="store_true")
    args = parser.parse_args()

    if args.version:
        from xklb import __version__

        print(__version__)
        stop()

    if args.limit == 1 and args.print:
        args.limit = None
    elif args.limit in ["inf", "all"]:
        args.limit = None

    if args.sort:
        args.sort = ' '.join(args.sort)

    if args.duration:
        SEC_TO_M = 60
        duration_m = 0
        duration_rules = ""

        for duration_rule in args.duration:
            if "+" in duration_rule:
                # min duration rule
                duration_rules += f"and duration >= {abs(int(duration_rule)) * SEC_TO_M} "
            elif "-" in duration_rule:
                # max duration rule
                duration_rules += f"and {abs(int(duration_rule)) * SEC_TO_M} >= duration "
            else:
                # approximate duration rule
                duration_m = int(duration_rule) * SEC_TO_M
                duration_rules += (
                    f"and {duration_m + (duration_m /10)} >= duration and duration >= {duration_m - (duration_m /10)} "
                )

        args.duration = duration_rules

    if args.size:
        B_TO_MB = 1024 * 1024
        size_mb = 0
        size_rules = ""

        for size_rule in args.size:
            if "+" in size_rule:
                # min size rule
                size_rules += f"and size >= {abs(int(args.size)) * B_TO_MB} "
            elif "-" in size_rule:
                # max size rule
                size_rules += f"and {abs(int(args.size)) * B_TO_MB} >= size "
            else:
                # approximate size rule
                size_mb = args.size * B_TO_MB
                size_rules += f"and {size_mb + (size_mb /10)} >= size and size >= {size_mb - (size_mb /10)} "

        args.size = size_rules

    YEAR_MONTH = lambda var: f"cast(strftime('%Y%m',datetime({var} / 1000000000, 'unixepoch')) as int)"
    if args.sort:
        args.sort = args.sort.replace("time_created", YEAR_MONTH("time_created"))
        args.sort = args.sort.replace("time_modified", YEAR_MONTH("time_modified"))
        args.sort = args.sort.replace("random", "random()")
        args.sort = args.sort.replace("priority", "round(duration / size,7)")
        args.sort = args.sort.replace("sub", "has_sub")

    args.where = [s.replace("sub", "has_sub") for s in args.where]

    if args.chromecast:
        args.cc_ip = get_ip_of_chromecast(args.chromecast_device)

    log.info({k: v for k, v in args.__dict__.items() if v})

    return args


def has_video(file_path):
    return (
        cmd(
            f"ffprobe -show_streams -select_streams v -loglevel error -i {quote(str(file_path))} | wc -l",
            shell=True,
        ).stdout
        > "0"
    )


def has_audio(file_path):
    return (
        cmd(
            f"ffprobe -show_streams -select_streams a -loglevel error -i {quote(str(file_path))} | wc -l", shell=True
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

    remove_media(args, str(media_file), quiet=True)


def post_act(args, media_file):
    if args.action == Subcommand.listen:
        args.con.execute("update media set listen_count = listen_count +1 where path = ?", (str(media_file),))
        args.con.commit()

    if args.post_action == "keep":
        pass
    elif args.post_action == "ask":
        if Confirm.ask("Keep?", default=False):
            mv_to_keep_folder(args, media_file)
    elif args.post_action == "delete":
        delete_media(args, media_file)
    elif args.post_action == "delete-if-audiobook":
        if "audiobook" in str(media_file).lower():
            delete_media(args, media_file)
    else:
        raise Exception("Unknown post_action", args.post_action)


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

    if "vlc" in args.player:
        catt_log = cmd(
            "vlc",
            "--sout",
            "#chromecast",
            f"--sout-chromecast-ip={args.cc_ip}",
            "--demux-filter=demux_chromecast",
            "--sub-file=" + subtitles_file if subtitles_file else "",
            *args.player[1:],
            media_file,
        )
    else:
        catt_log = cmd(
            "catt",
            "-d",
            args.chromecast_device,
            "cast",
            "-s",
            subtitles_file if subtitles_file else FAKE_SUBTITLE,
            media_file,
        )

    if subtitles_file:
        Path(subtitles_file).unlink(missing_ok=True)
    return catt_log


def listen_chromecast(args, media_file: Path, player):
    Path(CAST_NOW_PLAYING).write_text(str(media_file))
    Path(FAKE_SUBTITLE).touch()
    if not args.with_local:
        catt_log = cmd("catt", "-d", args.chromecast_device, "cast", "-s", FAKE_SUBTITLE, media_file)
    else:
        cast_process = subprocess.Popen(
            ["catt", "-d", args.chromecast_device, "cast", "-s", FAKE_SUBTITLE, media_file], preexec_fn=os.setpgrp
        )
        sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
        # if pyChromecast provides a way to sync accurately that would be very interesting to know; I have not researched it
        cmd_interactive(*player, "--", media_file)
        catt_log = Pclose(cast_process)  # wait for chromecast to stop (you can tell any chromecast to pause)
        sleep(3.0)  # give chromecast some time to breathe

    return catt_log


def play(args, media: pd.DataFrame):
    for m in media.to_records(index=False):
        media_file = m["path"]

        if args.play_in_order > 1 or (args.action == Subcommand.listen and "audiobook" in str(media_file).lower()):
            media_file = get_ordinal_media(args, Path(media_file))

        media_file = Path(args.prefix + media_file)
        if not media_file.exists():
            remove_media(args, str(media_file))
            continue

        if args.player:
            player = args.player
        elif which("mpv") is not None:
            player = ["mpv"]
            if args.action == Subcommand.listen:
                player.extend(
                    [f"--input-ipc-server={args.mpv_socket}", "--no-video", "--keep-open=no", "--really-quiet"]
                )
            elif args.action == Subcommand.watch:
                player.extend(["--fs", "--force-window=yes", "--really-quiet"])
        else:
            player = ["xdg-open"]

        if args.action == Subcommand.watch:
            if not has_video(media_file):
                print("[watch]: skipping non-video file", media_file)
                continue

            print(media_file)

        elif args.action == Subcommand.listen:
            if not has_audio(media_file):
                print("[listen]: skipping non-audio file", media_file)
                continue

            print(cmd("ffprobe", "-hide_banner", "-loglevel", "info", media_file).stderr)

        if args.transcode:
            media_file = transcode(media_file)

        if args.chromecast:
            if args.action == Subcommand.watch:
                catt_log = watch_chromecast(args, media_file)
            elif args.action == Subcommand.listen:
                catt_log = listen_chromecast(args, media_file, player)
            else:
                raise NotImplementedError

            if "Heartbeat timeout, resetting connection" in catt_log.stderr:
                raise Exception("Media is possibly partially unwatched")

            if catt_log.stderr == "":
                raise Exception("catt does not exit nonzero? but something might have gone wrong")

        else:
            if args.action == Subcommand.watch:
                if is_file_with_subtitle(media_file):
                    player.extend(args.player_args_when_sub)
                else:
                    player.extend(args.player_args_when_no_sub)

                cmd(*player, "--", media_file)
            elif args.action == Subcommand.listen:
                cmd_interactive(*player, "--", media_file)

        if args.post_action:
            post_act(args, media_file)


def construct_query(args):
    cf = []
    bindings = []

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    if args.action == Subcommand.listen:
        bindings = {}
        for idx, inc in enumerate(args.include):
            cf.append(audio_include_string(idx))
            bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
        for idx, exc in enumerate(args.exclude):
            cf.append(audio_exclude_string(idx))
            bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"
    else:
        for inc in args.include:
            cf.append(" AND path LIKE ? ")
            bindings.append("%" + inc.replace(" ", "%").replace("%%", " ") + "%")
        for exc in args.exclude:
            cf.append(" AND path NOT LIKE ? ")
            bindings.append("%" + exc.replace(" ", "%").replace("%%", " ") + "%")

    args.sql_filter = " ".join(cf)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""
    SELECT path
        {', duration/60/60 as hours' if args.action != Subcommand.filesystem else ''}
        {', duration / size AS seconds_per_byte' if args.action != Subcommand.filesystem else ''}
        , size
        {', sparseness' if args.action == Subcommand.filesystem else ''}
        {', is_dir' if args.action == Subcommand.filesystem else ''}
        {', ' + ', '.join(args.print_column) if args.print_column else ''}
    FROM media
    WHERE 1=1
    {args.sql_filter}
    {'and listen_count = 0' if args.action == Subcommand.listen and not args.include else ''}
    ORDER BY 1=1
        {', listen_count asc nulls first' if args.action == Subcommand.listen else ''}
        {',' + args.sort if args.sort else ''}
        {', path' if args.print or args.include or args.play_in_order > 0 else ''}
        {', seconds_per_byte ASC' if args.action != Subcommand.filesystem else ''}
    {LIMIT} {OFFSET}
    """

    return query, bindings


def printer(args, query):
    if "a" in args.print:
        query = f"""select
            "Aggregate" as path
            {', sum(hours) hours' if args.action != Subcommand.filesystem else ''}
            {', avg(seconds_per_byte) seconds_per_byte' if args.action != Subcommand.filesystem else ''}
            {', sparseness' if args.action == Subcommand.filesystem else ''}
            , sum(size) size
            , count(*) count
        from ({query}) """

    if args.print and "q" in args.print:
        print(query)
        stop()

    db_resp = pd.DataFrame([dict(r) for r in args.con.execute(query).fetchall()])

    if "f" in args.print:
        if args.limit == 1:
            f = db_resp[["path"]].loc[0].iat[0]
            if not Path(f).exists():
                remove_media(args, f)
                return printer(args, query)
            print(f)
        else:
            unix_loves_lines = db_resp[["path"]].to_csv(index=False, header=False, sep="\t", quoting=csv.QUOTE_NONE)
            print(unix_loves_lines.strip())
    else:
        db_resp[["path"]] = db_resp[["path"]].applymap(
            lambda x: textwrap.fill(x, os.get_terminal_size().columns - (18 * len(db_resp.columns)))
        )
        if "size" in db_resp.columns:
            db_resp[["size"]] = db_resp[["size"]].applymap(lambda x: None if x is None else humanize.naturalsize(x))
        if "time_modified" in db_resp.columns:
            db_resp[["time_modified"]] = db_resp[["time_modified"]].applymap(
                lambda x: None if x is None else humanize.naturaldate(datetime.fromtimestamp(x))
            )

        print(tabulate(db_resp, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore

        if args.action != Subcommand.filesystem:
            summary = db_resp.sum(numeric_only=True)
            hours = summary.get("hours") or 0.0
            duration = timedelta(hours=int(hours), minutes=math.ceil(hours % 1 * 60))  # type: ignore
            print("Total duration:", humanize.precisedelta(duration, minimum_unit="minutes"))

    stop()


def mover(args, media):
    Path(args.move).mkdir(exist_ok=True, parents=True)
    keep_path = str(Path(args.move).resolve())

    for media in media[["path"]]:
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


def watch():
    args = parse_args(default_chromecast="Living Room TV")
    args.action = Subcommand.watch
    if not args.db:
        args.db = "video.db"

    process_actions(args)


def listen():
    args = parse_args(default_chromecast="Xylo and Orchestra")
    args.action = Subcommand.listen
    if not args.db:
        args.db = "audio.db"

    try:
        process_actions(args)
    finally:
        if args.chromecast:
            Path(CAST_NOW_PLAYING).unlink(missing_ok=True)


def filesystem():
    args = parse_args()
    args.action = Subcommand.filesystem
    if not args.db:
        args.db = "fs.db"

    process_actions(args)
