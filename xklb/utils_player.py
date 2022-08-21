import os
import platform
import re
import shutil
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from platform import system
from random import randrange
from shutil import which
from time import sleep
from typing import Union

import humanize
import pandas as pd
from tabulate import tabulate

from xklb.utils import (
    CAST_NOW_PLAYING,
    FAKE_SUBTITLE,
    SC,
    SQLITE_PARAM_LIMIT,
    Pclose,
    chunks,
    cmd,
    cmd_interactive,
    conform,
    human_time,
    log,
    os_bg_kwargs,
    print_query,
    resize_col,
    single_column_tolist,
)


def mv_to_keep_folder(args, video):
    kp = re.match(args.shallow_organize + "(.*?)/", video)
    if kp:
        keep_path = Path(kp[0], "keep/")
    elif Path(video).parent.match("*/keep/*"):
        return
    else:
        keep_path = Path(video).parent / "keep/"

    keep_path.mkdir(exist_ok=True)
    shutil.move(video, keep_path)


def mark_media_watched(args, files):
    files = conform(files)
    if len(files) > 0:
        df_chunked = chunks(files, SQLITE_PARAM_LIMIT)
        for l in df_chunked:
            args.con.execute(
                """update media
                set play_count = play_count +1
                  , time_played = UNIXEPOCH()
                where path in ("""
                + ",".join(["?"] * len(l))
                + ")",
                (*l,),
            )
            args.con.commit()
    # TODO: return number of changed rows


def remove_media(args, deleted_files: Union[str, list], quiet=False):
    deleted_files = conform(deleted_files)
    if len(deleted_files) > 0:
        if not quiet:
            if len(deleted_files) == 1:
                print("Removing orphaned metadata", deleted_files[0])
            else:
                print(f"Removing {len(deleted_files)} orphaned metadata")

        df_chunked = chunks(deleted_files, SQLITE_PARAM_LIMIT)
        for l in df_chunked:
            args.con.execute(
                "delete from media where path in (" + ",".join(["?"] * len(l)) + ")",
                (*l,),
            )
            args.con.commit()
    # TODO: return number of changed rows


def delete_media(args, media_file: str):
    if len(args.prefix) > 0:
        Path(media_file).unlink()
    elif which("trash-put") is not None:
        cmd("trash-put", media_file, strict=False)
    else:
        Path(media_file).unlink()

    remove_media(args, media_file, quiet=True)


def delete_playlists(args, playlists):
    args.con.execute(
        "delete from media where playlist_path in (" + ",".join(["?"] * len(playlists)) + ")", (*playlists,)
    )
    args.con.execute("delete from playlists where path in (" + ",".join(["?"] * len(playlists)) + ")", (*playlists,))
    args.con.commit()


def get_ordinal_media(args, path):
    similar_videos = []
    candidate = str(path)

    total_media = args.con.execute("select count(*) val from media").fetchone()[0]
    while len(similar_videos) < 2:
        remove_groups = re.split(r"([\W]+|\s+|Ep\d+|x\d+|\.\d+)", candidate)
        log.debug(remove_groups)
        remove_chars = ""
        remove_chars_i = 1
        while len(remove_chars) < 1:
            remove_chars += remove_groups[-remove_chars_i]
            remove_chars_i += 1

        new_candidate = candidate[: -len(remove_chars)]
        log.debug(f"Matches for '{new_candidate}':")

        if candidate in ["" or new_candidate]:
            return path

        candidate = new_candidate
        query = f"""SELECT path FROM media
            WHERE 1=1
                and path like ?
                {'' if (args.play_in_order > 2) else args.sql_filter}
            ORDER BY path
            LIMIT 1000
            """
        bindings = ("%" + candidate + "%",)
        if args.print and "q" in args.print:
            print_query(bindings, query)
            exit()

        similar_videos = single_column_tolist(args.con.execute(query, bindings).fetchall(), "path")  # type: ignore
        log.debug(similar_videos)

        if len(similar_videos) > 999 or len(similar_videos) == total_media:
            return path

        commonprefix = os.path.commonprefix(similar_videos)
        log.debug(commonprefix)
        if len(Path(commonprefix).name) < 3:
            log.debug("Using commonprefix")
            return path

    return similar_videos[0]


def generic_player(args):
    if platform.system() == "Linux":
        player = ["xdg-open"]
    elif platform.system() == "Windows":
        if shutil.which("cygstart"):
            player = ["cygstart"]
        else:
            player = ["start", ""]
    else:
        player = ["open"]
    args.player_need_sleep = True
    return player


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


def watch_chromecast(args, m, subtitles_file=None):
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
        if args.action in [SC.watch, SC.listen]:
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
    if args.with_local:
        cast_process = subprocess.Popen(
            ["catt", "-d", args.chromecast_device, "cast", "-s", FAKE_SUBTITLE, m["path"]], **os_bg_kwargs()
        )
        sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
        # if pyChromecast provides a way to sync accurately that would be very interesting to know; I have not researched it
        cmd_interactive(*args.player, "--", m["path"])
        catt_log = Pclose(cast_process)  # wait for chromecast to stop (you can tell any chromecast to pause)
        sleep(3.0)  # give chromecast some time to breathe
    else:
        if args.action in [SC.watch, SC.listen]:
            catt_log = cmd("catt", "-d", args.chromecast_device, "cast", "-s", FAKE_SUBTITLE, m["path"])
        else:  # args.action in [SC.tubewatch, SC.tubelisten]:
            catt_log = args.cc.play_url(m["path"], resolve=True, block=True)

    return catt_log


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
    except Exception:
        pass
    if end == 0:
        return

    play_opts = f"start={start},save-position-on-quit=no"
    if args.action in [SC.listen, SC.tubelisten]:
        play_opts += ",video=no,really-quiet=yes"
    elif args.action in [SC.watch, SC.tubewatch]:
        play_opts += ",fullscreen=yes,force-window=yes,really-quiet=yes"

    if args.action in [SC.tubelisten, SC.tubewatch]:
        play_opts += ",script-opts=ytdl_hook-try_ytdl_first=yes"

    f = m.path.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    args.sock.send((f'raw loadfile "{f}" replace "{play_opts}" \n').encode("utf-8"))
    sleep(args.interdimensional_cable)


def local_player(args, m, media_file):
    args.player_need_sleep = False
    player = generic_player(args)

    if args.player:
        player = args.player
    elif which("mpv"):
        player = [which("mpv")]
        if args.action in [SC.listen, SC.tubelisten]:
            player.extend([f"--input-ipc-server={args.mpv_socket}", "--no-video", "--keep-open=no", "--really-quiet"])
        elif args.action in [SC.watch, SC.tubewatch]:
            player.extend(["--fs", "--force-window=yes", "--really-quiet"])

        if args.action in [SC.tubelisten, SC.tubewatch]:
            player.extend(["--script-opts=ytdl_hook-try_ytdl_first=yes"])

        start, end = calculate_duration(args, m)
        if end == 0:
            return
        if start != 0:
            player.extend([f"--start={int(start)}", "--no-save-position-on-quit"])
        if end != m.duration:
            player.extend([f"--end={int(end)}"])
    elif system() == "Linux":
        mimetype = cmd("xdg-mime", "query", "filetype", media_file).stdout
        default_application = cmd("xdg-mime", "query", "default", mimetype).stdout
        player_path = which(default_application.replace(".desktop", ""))
        if player_path:
            player = [player_path]

    if args.action == SC.watch:
        if m["subtitle_count"] > 0:
            player.extend(args.player_args_when_sub)
        else:
            player.extend(args.player_args_when_no_sub)

    if system() == "Windows" or args.action in [SC.watch, SC.tubewatch]:
        r = cmd(*player, media_file, strict=False)
    else:  # args.action in [SC.listen, SC.tubelisten]
        r = cmd_interactive(*player, media_file, strict=False)
    if r.returncode != 0:
        print("Player exited with code", r.returncode)
        if not args.ignore_errors:
            exit(4)

    if args.player_need_sleep:
        if hasattr(m, "duration"):
            delay = m.duration
        else:
            delay = 10
        sleep(delay)


def printer(args, query, bindings):
    if "a" in args.print:
        query = f"""select
            "Aggregate" as path
            {', sum(duration) duration' if args.action in [SC.listen, SC.watch, SC.tubelisten, SC.tubewatch] else ''}
            {', sparseness' if args.action == SC.filesystem else ''}
            {', sum(size) size' if args.action != SC.tabs else ''}
            , count(*) count
            {', ' + ', '.join([f'sum({c}) sum_{c}' for c in args.cols]) if args.cols else ''}
            {', ' + ', '.join([f'avg({c}) avg_{c}' for c in args.cols]) if args.cols else ''}
        from ({query}) """

    if args.print and "q" in args.print:
        return print(query)

    db_resp = pd.DataFrame([dict(r) for r in args.con.execute(query, bindings).fetchall()])
    db_resp.dropna(axis="columns", how="all", inplace=True)

    if args.verbose > 1 and args.cols and "*" in args.cols:
        import rich

        breakpoint()
        for t in db_resp.to_dict(orient="records"):
            rich.print(t)

    if db_resp.empty or len(db_resp) == 0:
        print("No media found")
        exit(2)

    if "d" in args.print:
        remove_media(args, db_resp[["path"]].values.tolist(), quiet=True)
        if not "f" in args.print:
            return print(f"Removed {len(db_resp)} metadata records")

    if "w" in args.print:
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
            if not args.cols:
                args.cols = ["path"]

            for line in db_resp[[*args.cols]].to_string(index=False, header=False).splitlines():
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

        for t in ["time_modified", "time_created", "time_played", "time_valid"]:
            if t in tbl.columns:
                tbl[[t]] = tbl[[t]].applymap(
                    lambda x: None if x is None else humanize.naturaldate(datetime.fromtimestamp(x))
                )

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore

        if args.action in [SC.listen, SC.watch, SC.tubelisten, SC.tubewatch]:
            if len(db_resp) > 1:
                print(f"{len(db_resp)} items")
            summary = db_resp.sum(numeric_only=True)
            duration = summary.get("duration") or 0
            duration = human_time(duration)
            print("Total duration:", duration)
