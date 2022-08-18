import argparse
import os
from platform import system
import shlex
import shutil
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from random import randrange
from shutil import which
from time import sleep

import ffmpeg
import humanize
import pandas as pd
import psutil
import sqlite_utils
from catt.api import CattDevice
from rich.prompt import Confirm
from tabulate import tabulate

from xklb.db import sqlite_con
from xklb.utils import (
    CAST_NOW_PLAYING,
    DEFAULT_MPV_SOCKET,
    FAKE_SUBTITLE,
    Pclose,
    Subcommand,
    audio_exclude_string,
    audio_include_string,
    cmd,
    cmd_interactive,
    filter_None,
    flatten,
    get_ip_of_chromecast,
    get_ordinal_media,
    human_time,
    log,
    mark_media_watched,
    mv_to_keep_folder,
    os_bg_kwargs,
    remove_media,
    resize_col,
    tube_exclude_string,
    tube_include_string,
)

idle_mpv = lambda args: ["mpv", "--idle", f"--input-ipc-server={args.mpv_socket}"]

DEFAULT_PLAY_QUEUE = 120

pd.set_option("display.float_format", lambda x: "%.5f" % x)


def override_sort(string):
    YEAR_MONTH = lambda var: f"cast(strftime('%Y%m',datetime({var} / 1000000000, 'unixepoch')) as int)"

    return (
        string.replace("month_created", YEAR_MONTH("time_created"))
        .replace("month_modified", YEAR_MONTH("time_modified"))
        .replace("random", "random()")
        .replace("priority", "play_count, round(duration / size,7)")
    )


def parse_args(default_db, default_chromecast=""):
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument(
        "database",
        nargs="?",
        default=default_db,
        help="Database file. If not specified a generic name will be used: audio.db, video.db, fs.db, etc",
    )

    # TODO: maybe try https://dba.stackexchange.com/questions/43415/algorithm-for-finding-the-longest-prefix
    parser.add_argument(
        "--play-in-order",
        "-O",
        action="count",
        default=0,
        help="Try to get things to play in order -- similarly named episodes",
    )
    parser.add_argument(
        "--duration",
        "-d",
        action="append",
        help="""Media duration in minutes:
-d 6 means 6 mins ±10 percent -- between 5 and 7 mins
-d-6 means less than 6 mins
-d+6 means more than 6 mins

-d+5 -d-7 should be similar to -d 6

if you want exact times you can use --where duration=6*60
""",
    )
    parser.add_argument(
        "--sort",
        "-u",
        nargs="+",
        default=["priority"],
        help="""Sort media with SQL expressions
-u duration means shortest media first
-u duration desc means longest media first

You can use any sqlite ORDER BY expressions, for example:
-u subtitle_count > 0
means play everything that has a subtitle first
""",
    )
    parser.add_argument(
        "--where",
        "-w",
        nargs="+",
        action="extend",
        default=[],
        help="""Constrain media with SQL expressions
You can use any sqlite WHERE expressions, for example:
-w attachment_count > 0  means only media with attachments
-w language = 'eng'  means only media which has some English language tag -- this could be audio or subtitle""",
    )
    parser.add_argument(
        "--include",
        "-s",
        "--search",
        nargs="+",
        action="extend",
        default=[],
        help="""Constrain media with via search
-s toy story will match '/folder/toy/something/story.mp3'
-s 'toy  story' will match more strictly '/folder/toy story.mp3'
Double spaces means one space
""",
    )
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[])

    parser.add_argument(
        "--delete",
        "--remove",
        "--erase",
        "--rm",
        "-rm",
        action="store_true",
        help="lb tw -s 'something to delete' -rm",
    )
    parser.add_argument(
        "--mark-watched",
        "--watched",
        "--mark-played",
        "--played",
        action="store_true",
        help="lb wt -s 'something to mark seen' --mark-watched",
    )

    parser.add_argument(
        "--chromecast-device",
        "-cast-to",
        default=default_chromecast,
        help="The name of your chromecast device or group. Use exact uppercase/lowercase",
    )
    parser.add_argument(
        "--chromecast", "-cast", action="store_true", help="Turn chromecast on. Use like this: lt -cast or tl -cast"
    )
    parser.add_argument(
        "--with-local",
        "-wl",
        action="store_true",
        help="Play with local speakers and chromecast at the same time [experimental]",
    )
    parser.add_argument(
        "--interdimensional-cable",
        "-4dtv",
        type=int,
        help="Duration to play (in seconds) while changing the channel [experimental]",
    )
    parser.add_argument("--portrait", "-portrait", action="store_true")

    parser.add_argument("--prefix", default="", help="change root prefix; useful for sshfs")

    parser.add_argument("--size", "-z", action="append", help="Constrain media with via size in Megabytes")

    parser.add_argument(
        "--print",
        "-p",
        default=False,
        const="p",
        nargs="?",
        help="""Print instead of play
-p   means print in a table
-p a means print an aggregate report
-p f means print only filenames -- useful for piping to other utilities like xargs or GNU Parallel""",
    )
    parser.add_argument("--print-column", "-col", nargs="*", help="Include a non-standard column when printing")
    parser.add_argument(
        "--limit", "-L", "-l", "-queue", "--queue", default=DEFAULT_PLAY_QUEUE, help="Set play queue size"
    )
    parser.add_argument("--skip", "-S", help="Offset from the top of an ordered query; wt -S10 to skip ten videos")

    parser.add_argument(
        "--start", "-vs", help='Set the time to skip from the start of the media or use the magic word "wadsworth"'
    )
    parser.add_argument(
        "--end", "-ve", help='Set the time to skip from the end of the media or use the magic word "dawsworth"'
    )
    parser.add_argument("--player", "-player", help='Override the default player; wt --player "vlc --vlc-opts"')
    parser.add_argument("--mpv-socket", default=DEFAULT_MPV_SOCKET)

    parser.add_argument(
        "--player-args-when-sub",
        "-player-sub",
        nargs="*",
        default=["--speed=1"],
        help="Only give args for videos with subtitles",
    )
    parser.add_argument(
        "--player-args-when-no-sub",
        "-player-no-sub",
        nargs="*",
        default=["--speed=1.7"],
        help="Only give args for videos without subtitles",
    )
    parser.add_argument("--transcode", action="store_true")

    parser.add_argument("--post-action", "--action", "-k", default="keep", help="Choose what to do after playing")
    parser.add_argument("--shallow-organize", default="/mnt/d/")

    parser.add_argument("--db", "-db")
    parser.add_argument("--ignore-errors", "--ignoreerrors", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    if args.db:
        args.database = args.db

    if args.limit == DEFAULT_PLAY_QUEUE and args.print:
        args.limit = None
    elif args.limit in ["inf", "all"]:
        args.limit = None

    if args.sort:
        args.sort = " ".join(args.sort)

    if args.print_column:
        args.print_column = list(flatten([s.split(",") for s in args.print_column]))

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

    if args.sort:
        args.sort = override_sort(args.sort)

    if args.chromecast:
        args.cc = CattDevice(args.chromecast_device, lazy=True)
        args.cc_ip = get_ip_of_chromecast(args.chromecast_device)

    if args.player:
        args.player = shlex.split(args.player)

    log.info(filter_None(args.__dict__))

    args.sock = None
    return args


def transcode(next_video):
    temp_video = cmd("mktemp", "--suffix=.mkv", "--dry-run").stdout.strip()
    shutil.move(next_video, temp_video)
    next_video = str(Path(next_video).with_suffix(".mkv"))
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


def delete_media(args, media_file: str):
    if len(args.prefix) > 0:
        Path(media_file).unlink()
    elif which("trash-put") is not None:
        cmd("trash-put", media_file, strict=False)
    else:
        Path(media_file).unlink()

    remove_media(args, media_file, quiet=True)


def post_act(args, media_file: str):
    if args.action in [Subcommand.listen, Subcommand.watch, Subcommand.tubelisten, Subcommand.tubewatch]:
        mark_media_watched(args, media_file)

    if args.post_action == "keep":
        pass
    elif args.post_action == "ask":
        if not Confirm.ask("Keep?", default=False):
            delete_media(args, media_file)
    elif args.post_action == "askkeep":
        if not Confirm.ask("Keep?", default=False):
            delete_media(args, media_file)
        else:
            mv_to_keep_folder(args, media_file)
    elif args.post_action == "delete":
        delete_media(args, media_file)
    elif args.post_action == "delete-if-audiobook":
        if "audiobook" in str(media_file).lower():
            delete_media(args, media_file)
    else:
        raise Exception("Unknown post_action", args.post_action)


def externalize_subtitle(media_file):
    subs = ffmpeg.probe(media_file)["streams"]

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


def watch_chromecast(args, m):
    subtitles_file = externalize_subtitle(m["path"])

    if "vlc" in args.player:
        catt_log = cmd(
            "vlc",
            "--sout",
            "#chromecast",
            f"--sout-chromecast-ip={args.cc_ip}",
            "--demux-filter=demux_chromecast",
            "--sub-file=" + subtitles_file if subtitles_file else "",
            *args.player[1:],
            m["path"],
        )
    else:
        if args.action in [Subcommand.watch, Subcommand.listen]:
            catt_log = cmd(
                "catt",
                "-d",
                args.chromecast_device,
                "cast",
                "-s",
                subtitles_file if subtitles_file else FAKE_SUBTITLE,
                m["path"],
            )
        else:
            catt_log = args.cc.play_url(m["path"], resolve=True, block=True)

    if subtitles_file:
        Path(subtitles_file).unlink(missing_ok=True)
    return catt_log


def listen_chromecast(args, m):
    Path(CAST_NOW_PLAYING).write_text(m["path"])
    Path(FAKE_SUBTITLE).touch()
    if not args.with_local:
        if args.action in [Subcommand.watch, Subcommand.listen]:
            catt_log = cmd("catt", "-d", args.chromecast_device, "cast", "-s", FAKE_SUBTITLE, m["path"])
        else:
            catt_log = args.cc.play_url(m["path"], resolve=True, block=True)
    else:
        cast_process = subprocess.Popen(
            ["catt", "-d", args.chromecast_device, "cast", "-s", FAKE_SUBTITLE, m["path"]], **os_bg_kwargs()
        )
        sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
        # if pyChromecast provides a way to sync accurately that would be very interesting to know; I have not researched it
        cmd_interactive(*args.player, "--", m["path"])
        catt_log = Pclose(cast_process)  # wait for chromecast to stop (you can tell any chromecast to pause)
        sleep(3.0)  # give chromecast some time to breathe

    return catt_log


def calculate_duration(args, m):
    start = 0
    end = m.duration

    if args.start:
        if args.start == "wadsworth":
            start = m.duration * 0.3
        else:
            start = args.start
    if args.end:
        if args.end == "dawsworth":
            end = m.duration * 0.65
        elif "+" in args.end:
            end = (m.duration * 0.3) + args.end
        else:
            end = args.end

    return start, end


def socket_play(args, m):
    if args.sock is None:
        subprocess.Popen(["mpv", "--idle", "--input-ipc-server=" + args.mpv_socket])
        while not os.path.exists(args.mpv_socket):
            sleep(0.2)
        args.sock = socket.socket(socket.AF_UNIX)
        args.sock.connect(args.mpv_socket)

    start, end = calculate_duration(args, m)

    try:
        bias_to_acts = m.index + 1 / args.limit
        start = randrange(int(start * bias_to_acts), int(end - args.interdimensional_cable + 1))
        end = start + args.interdimensional_cable
    except:
        pass
    if end == 0:
        return

    play_opts = f"start={start},save-position-on-quit=no"
    if args.action in [Subcommand.listen, Subcommand.tubelisten]:
        play_opts += ",video=no,really-quiet=yes"
    elif args.action in [Subcommand.watch, Subcommand.tubewatch]:
        play_opts += ",fullscreen=yes,force-window=yes,really-quiet=yes"

    if args.action in [Subcommand.tubelisten, Subcommand.tubewatch]:
        play_opts += ",script-opts=ytdl_hook-try_ytdl_first=yes"

    f = m.path.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    args.sock.send((f'raw loadfile "{f}" replace "{play_opts}" \n').encode("utf-8"))
    sleep(args.interdimensional_cable)


def local_player(args, m, media_file):
    if args.player:
        player = args.player
    elif which("mpv"):
        player = [which("mpv")]
        if args.action in [Subcommand.listen, Subcommand.tubelisten]:
            player.extend([f"--input-ipc-server={args.mpv_socket}", "--no-video", "--keep-open=no", "--really-quiet"])
        elif args.action in [Subcommand.watch, Subcommand.tubewatch]:
            player.extend(["--fs", "--force-window=yes", "--really-quiet"])

        if args.action in [Subcommand.tubelisten, Subcommand.tubewatch]:
            player.extend(["--script-opts=ytdl_hook-try_ytdl_first=yes"])

        start, end = calculate_duration(args, m)
        if end == 0:
            return
        if start != 0:
            player.extend([f"--start={int(start)}", "--no-save-position-on-quit"])
        if end != m.duration:
            player.extend([f"--end={int(end)}"])
    elif system() == 'Linux':
        mimetype = cmd('xdg-mime', 'query', 'filetype', media_file).stdout
        default_application = cmd('xdg-mime', 'query', 'default', mimetype).stdout
        player_path = which(default_application.replace('.desktop',''))
        if player_path:
            player = [player_path]
        else:
            player = ["xdg-open"]
            sleep(m.duration)
    elif system() == "Windows":
        if which("cygstart"):
            player = ["cygstart"]
        else:
            player = ["start", ""]
        sleep(m.duration)
    else:
        player = ["open"]
        sleep(m.duration)

    if args.action == Subcommand.watch:
        if m["subtitle_count"] > 0:
            player.extend(args.player_args_when_sub)
        else:
            player.extend(args.player_args_when_no_sub)

    if system() == "Windows":
        r = cmd(*player, media_file, strict=False)
    elif args.action in [Subcommand.watch, Subcommand.tubewatch]:
        r = cmd(*player, "--", media_file, strict=False)
    else: # args.action in [Subcommand.listen, Subcommand.tubelisten]
        r = cmd_interactive(*player, "--", media_file, strict=False)
    if r.returncode != 0:
        print('Player exited with code', r.returncode)
        if not args.ignore_errors:
            exit(4)


def chromecast_play(args, m):
    if args.action in [Subcommand.watch, Subcommand.tubewatch]:
        catt_log = watch_chromecast(args, m)
    elif args.action in [Subcommand.listen, Subcommand.tubelisten]:
        catt_log = listen_chromecast(args, m)
    else:
        raise NotImplementedError

    if catt_log:
        if "Heartbeat timeout, resetting connection" in catt_log.stderr:
            raise Exception("Media is possibly partially unwatched")

        if catt_log.stderr == "":
            raise Exception("catt does not exit nonzero? but something might have gone wrong")


def play(args, media: pd.DataFrame):
    for m in media.to_records():
        media_file = m["path"]

        if any(
            [
                args.play_in_order > 1 and args.action not in [Subcommand.listen, Subcommand.tubelisten],
                args.play_in_order >= 1 and args.action == Subcommand.listen and "audiobook" in media_file.lower(),
                args.play_in_order >= 1
                and args.action == Subcommand.tubelisten
                and m["title"]
                and "audiobook" in m["title"].lower(),
            ]
        ):
            media_file = get_ordinal_media(args, media_file)

        if not media_file.startswith("http"):
            media_path = Path(args.prefix + media_file).resolve()
            if not media_path.exists():
                remove_media(args, media_file)
                continue
            media_file = str(media_path)

            if args.transcode:
                media_file = transcode(media_file)

        if args.action in [Subcommand.watch, Subcommand.tubewatch]:
            print(media_file)
        elif args.action == Subcommand.listen:
            print(cmd("ffprobe", "-hide_banner", "-loglevel", "info", media_file).stderr)

        if args.chromecast:
            chromecast_play(args, m)

        elif args.interdimensional_cable:
            socket_play(args, m)

        else:
            local_player(args, m, media_file)

        if args.post_action and not args.interdimensional_cable:
            post_act(args, media_file)


def construct_query(args):
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    if args.action == Subcommand.listen:
        for idx, inc in enumerate(args.include):
            cf.append(audio_include_string(idx))
            bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
        for idx, exc in enumerate(args.exclude):
            cf.append(audio_exclude_string(idx))
            bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"
    elif args.action in [Subcommand.tubewatch, Subcommand.tubelisten]:
        for idx, inc in enumerate(args.include):
            cf.append(tube_include_string(idx))
            bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
        for idx, exc in enumerate(args.exclude):
            cf.append(tube_exclude_string(idx))
            bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"
    else:
        bindings = []
        for inc in args.include:
            cf.append(" AND path LIKE ? ")
            bindings.append("%" + inc.replace(" ", "%").replace("%%", " ") + "%")
        for exc in args.exclude:
            cf.append(" AND path NOT LIKE ? ")
            bindings.append("%" + exc.replace(" ", "%").replace("%%", " ") + "%")

    args.sql_filter = " ".join(cf)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""SELECT path
        {', duration' if args.action != Subcommand.filesystem else ''}
        {', subtitle_count' if args.action == Subcommand.watch else ''}
        , size
        {', ' + ', '.join(args.print_column) if args.print_column else ''}
        {', sparseness' if args.action == Subcommand.filesystem else ''}
        {', is_dir' if args.action == Subcommand.filesystem else ''}
        {', title' if args.action in [Subcommand.tubelisten, Subcommand.tubewatch] else ''}
        {', ' + ', '.join(args.print_column) if args.print_column else ''}
    FROM media
    WHERE 1=1
    {args.sql_filter}
    {'and audio_count > 0' if args.action == Subcommand.listen else ''}
    {'and video_count > 0' if args.action == Subcommand.watch else ''}
    {'and path not like "%/keep/%"' if args.post_action == 'askkeep' else ''}
    {'and width < height' if args.portrait else ''}
    ORDER BY 1=1
        {',' + args.sort if args.sort else ''}
        {', path' if args.print or args.include or args.play_in_order > 0 else ''}
        {', duration / size ASC' if args.action != Subcommand.filesystem else ''}
    {LIMIT} {OFFSET}
    """

    return query, bindings


def printer(args, query, bindings):
    if "a" in args.print:
        query = f"""select
            "Aggregate" as path
            {', sum(duration) duration' if args.action != Subcommand.filesystem else ''}
            {', sparseness' if args.action == Subcommand.filesystem else ''}
            , sum(size) size
            , count(*) count
            {', ' + ', '.join([f'sum({c}) sum_{c}' for c in args.print_column]) if args.print_column else ''}
            {', ' + ', '.join([f'avg({c}) avg_{c}' for c in args.print_column]) if args.print_column else ''}
        from ({query}) """

    if args.print and "q" in args.print:
        return print(query)

    db_resp = pd.DataFrame([dict(r) for r in args.con.execute(query, bindings).fetchall()])
    db_resp.dropna(axis="columns", how="all", inplace=True)

    if args.verbose > 1 and args.print_column and "*" in args.print_column:
        import rich

        breakpoint()
        for t in db_resp.to_dict(orient="records"):
            rich.print(t)

    if db_resp.empty or len(db_resp) == 0:
        print("No media found")
        exit(2)

    if args.delete:
        remove_media(args, db_resp[["path"]].values.tolist(), quiet=True)
        if not "f" in args.print:
            return print(f"Deleted {len(db_resp)} metadata records")

    if args.mark_watched:
        mark_media_watched(args, db_resp[["path"]].values.tolist())
        if not "f" in args.print:
            return print(f"{len(db_resp)} metadata records marked watched")

    if "f" in args.print:
        if args.limit == 1:
            f = db_resp[["path"]].loc[0].iat[0]
            if not Path(f).exists():
                remove_media(args, f)
                return printer(args, query, bindings)
            print(f)
        else:
            if not args.print_column:
                args.print_column = ["path"]

            for line in db_resp[[*args.print_column]].to_string(index=False, header=False).splitlines():
                print(line.strip())
    else:
        tbl = db_resp.copy()
        resize_col(tbl, "path", 22)
        resize_col(tbl, "title", 18)

        if "size" in tbl.columns:
            tbl[["size"]] = tbl[["size"]].applymap(lambda x: None if x is None else humanize.naturalsize(x))

        if "duration" in tbl.columns:
            tbl[["duration"]] = tbl[["duration"]].applymap(human_time)
        resize_col(tbl, "duration", 6)

        for t in ["time_modified", "time_created"]:
            if t in tbl.columns:
                tbl[[t]] = tbl[[t]].applymap(
                    lambda x: None if x is None else humanize.naturaldate(datetime.fromtimestamp(x))
                )

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore

        if args.action != Subcommand.filesystem:
            if len(db_resp) > 1:
                print(f"{len(db_resp)} items")
            summary = db_resp.sum(numeric_only=True)
            duration = summary.get("duration") or 0
            duration = human_time(duration)
            print("Total duration:", duration)


def pkill(*command, strict=True):
    found = 0
    for process in psutil.process_iter():
        if process.cmdline() == command:
            process.terminate()
            found = 1
            break
    if strict and found == 0:
        raise Exception("Process not found")


def process_actions(args):
    args.con = sqlite_con(args.database)
    query, bindings = construct_query(args)

    if args.print:
        return printer(args, query, bindings)

    media = pd.DataFrame([dict(r) for r in args.con.execute(query, bindings).fetchall()])
    if len(media) == 0:
        print("No media found")
        exit(2)

    if args.interdimensional_cable:
        subprocess.Popen(idle_mpv(args))

    try:
        play(args, media)
    finally:
        if args.interdimensional_cable:
            pkill(idle_mpv(args), strict=False)
        Path(args.mpv_socket).unlink(missing_ok=True)
        if args.chromecast:
            Path(CAST_NOW_PLAYING).unlink(missing_ok=True)


def watch():
    args = parse_args("video.db", default_chromecast="Living Room TV")
    args.action = Subcommand.watch
    process_actions(args)


def listen():
    args = parse_args("audio.db", default_chromecast="Xylo and Orchestra")
    args.action = Subcommand.listen
    process_actions(args)


def filesystem():
    args = parse_args("fs.db")
    args.action = Subcommand.filesystem
    process_actions(args)
