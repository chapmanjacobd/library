import os, platform, re, shutil, socket, subprocess
from datetime import datetime
from pathlib import Path
from platform import system
from random import randrange
from shlex import quote
from shutil import which
from time import sleep
from typing import Union

import humanize
import pandas as pd
from tabulate import tabulate

from xklb import paths, utils
from xklb.utils import SC, SQLITE_PARAM_LIMIT, cmd, cmd_interactive, human_time, log, os_bg_kwargs, resize_col


def mv_to_keep_folder(args, media_file: str):
    keep_path = Path(args.keep_dir)
    if not keep_path.is_absolute():
        kp = re.match(args.shallow_organize + "(.*?)/", media_file)
        if kp:
            keep_path = Path(kp[0], f"{args.keep_dir}/")
        elif Path(media_file).parent.match(f"*/{args.keep_dir}/*"):
            return
        else:
            keep_path = Path(media_file).parent / f"{args.keep_dir}/"

    keep_path.mkdir(exist_ok=True)
    new_path = shutil.move(media_file, keep_path)
    with args.db.conn:
        args.db.conn.execute("UPDATE media set path = ? where path = ?", [new_path, media_file])


def mark_media_watched(args, files):
    files = utils.conform(files)
    modified_row_count = 0
    if len(files) > 0:
        df_chunked = utils.chunks(files, SQLITE_PARAM_LIMIT)
        for l in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    """UPDATE media
                    set play_count = play_count +1
                    , time_played = cast(STRFTIME('%s') as int)
                    where path in ("""
                    + ",".join(["?"] * len(l))
                    + ")",
                    (*l,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def mark_media_deleted(args, files):
    files = utils.conform(files)
    modified_row_count = 0
    if len(files) > 0:
        df_chunked = utils.chunks(files, SQLITE_PARAM_LIMIT)
        for l in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    """update media
                    set is_deleted=1
                    where path in ("""
                    + ",".join(["?"] * len(l))
                    + ")",
                    (*l,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def moved_media(args, moved_files: Union[str, list], base_from, base_to):
    moved_files = utils.conform(moved_files)
    modified_row_count = 0
    if len(moved_files) > 0:
        df_chunked = utils.chunks(moved_files, SQLITE_PARAM_LIMIT)
        for l in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""UPDATE media
                    SET path=REPLACE(path, '{quote(base_from)}', '{quote(base_to)}')
                    where path in ("""
                    + ",".join(["?"] * len(l))
                    + ")",
                    (*l,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def remove_media(args, deleted_files: Union[str, list], quiet=False):
    deleted_files = utils.conform(deleted_files)
    modified_row_count = 0
    if len(deleted_files) > 0:
        if not quiet:
            if len(deleted_files) == 1:
                print(f"[{deleted_files[0]}] Removing orphaned metadata")
            else:
                print(f"Removing {len(deleted_files)} orphaned metadata")

        df_chunked = utils.chunks(deleted_files, SQLITE_PARAM_LIMIT)
        for l in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    "delete from media where path in (" + ",".join(["?"] * len(l)) + ")",
                    (*l,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def delete_media(args, media_file: str):
    if len(args.prefix) > 0:
        Path(media_file).unlink()
    elif which("trash-put") is not None:
        cmd("trash-put", media_file, strict=False)
    else:
        Path(media_file).unlink()

    mark_media_deleted(args, media_file)


def delete_playlists(args, playlists):
    with args.db.conn:
        args.db.conn.execute(
            "delete from media where playlist_path in (" + ",".join(["?"] * len(playlists)) + ")", (*playlists,)
        )
        args.db.conn.execute("delete from playlists where path in (" + ",".join(["?"] * len(playlists)) + ")", (*playlists,))


def get_ordinal_media(args, path):
    similar_videos = []
    candidate = str(path)

    total_media = args.db.execute("select count(*) val from media").fetchone()[0]
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
                {'and is_deleted=0' if args.action in [SC.listen, SC.watch] else ''}
                {'' if (args.play_in_order > 2) else (args.sql_filter or '')}
            ORDER BY path
            LIMIT 1000
            """
        bindings = ["%" + candidate + "%"]
        if not args.play_in_order > 2:
            bindings.extend(args.sql_filter_bindings)

        similar_videos = [d["path"] for d in args.db.query(query, bindings)]
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
    end = m["duration"]

    if args.start:
        if args.start == "wadsworth":
            start = m["duration"] * 0.3
        else:
            start = args.start
    if args.end:
        if args.end == "dawsworth":
            end = m["duration"] * 0.65
        elif "+" in args.end:
            end = (m["duration"] * 0.3) + args.end
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
                subtitles_file if subtitles_file else paths.FAKE_SUBTITLE,
                m["path"],
            )
        else:
            catt_log = args.cc.play_url(m["path"], resolve=True, block=True)

    if subtitles_file:
        Path(subtitles_file).unlink(missing_ok=True)
    return catt_log


def listen_chromecast(args, m):
    Path(paths.CAST_NOW_PLAYING).write_text(m["path"])
    Path(paths.FAKE_SUBTITLE).touch()
    if args.with_local:
        cast_process = subprocess.Popen(
            ["catt", "-d", args.chromecast_device, "cast", "-s", paths.FAKE_SUBTITLE, m["path"]], **os_bg_kwargs()
        )
        sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
        # if pyChromecast provides a way to sync accurately that would be very interesting to know; I have not researched it
        cmd_interactive(*args.player, "--", m["path"])
        catt_log = utils.Pclose(cast_process)  # wait for chromecast to stop (you can tell any chromecast to pause)
        sleep(3.0)  # give chromecast some time to breathe
    else:
        if args.action in [SC.watch, SC.listen]:
            catt_log = cmd("catt", "-d", args.chromecast_device, "cast", "-s", paths.FAKE_SUBTITLE, m["path"])
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
        start = randrange(int(start), int(end - args.interdimensional_cable + 1))
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

    f = m["path"].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    args.sock.send((f'raw loadfile "{f}" replace "{play_opts}" \n').encode("utf-8"))
    sleep(args.interdimensional_cable)


def local_player(args, m, media_file):
    player = generic_player(args)
    mpv = which("mpv.com") or which("mpv")

    if args.player:
        player = args.player
        args.player_need_sleep = False

    elif mpv:
        args.player_need_sleep = False
        player = [mpv]
        if args.action in [SC.listen, SC.tubelisten]:
            player.extend([f"--input-ipc-server={args.mpv_socket}", "--no-video", "--keep-open=no", "--really-quiet"])
        elif args.action in [SC.watch, SC.tubewatch]:
            player.extend(["--fs", "--force-window=yes", "--really-quiet"])

        if args.action in [SC.tubelisten, SC.tubewatch]:
            player.extend(["--script-opts=ytdl_hook-try_ytdl_first=yes"])

        if args.action in [SC.watch, SC.listen]:
            start, end = calculate_duration(args, m)
            if end == 0:
                return
            if start != 0:
                player.extend([f"--start={int(start)}", "--no-save-position-on-quit"])
            if end != m["duration"]:
                player.extend([f"--end={int(end)}"])

    elif system() == "Linux":
        mimetype = cmd("xdg-mime", "query", "filetype", media_file).stdout
        default_application = cmd("xdg-mime", "query", "default", mimetype).stdout
        player_path = which(default_application.replace(".desktop", ""))
        if player_path:
            args.player_need_sleep = False
            player = [player_path]

    if args.action == SC.watch:
        if m["subtitle_count"] > 0:
            player.extend(args.player_args_when_sub)
        elif Path(media_file).stat().st_size > 500 * 1000000:  # 500 MB
            # player.extend(args.player_args_when_no_sub_big_file) # TODO: if people complain fix this
            pass
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
            delay = m["duration"]
        else:
            delay = 10  # TODO: idk
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

    db_resp = pd.DataFrame(args.db.query(query, bindings))
    db_resp.dropna(axis="columns", how="all", inplace=True)

    if args.verbose > 1 and args.cols and "*" in args.cols:
        breakpoint()

    if db_resp.empty or len(db_resp) == 0:
        print("No media found")
        exit(2)

    if "d" in args.print:
        remove_media(args, db_resp[["path"]].values.tolist(), quiet=True)
        if not "f" in args.print:
            return print(f"Removed {len(db_resp)} metadata records")

    if "w" in args.print:
        marked = mark_media_watched(args, db_resp[["path"]].values.tolist())
        if not "f" in args.print:
            return print(f"Marked {marked} metadata records as watched")

    if "f" in args.print:
        if args.limit == 1:
            f = db_resp[["path"]].loc[0].iat[0]
            if not Path(f).exists():
                mark_media_deleted(args, f)
                return printer(args, query, bindings)
            print(f)
        else:
            if not args.cols:
                args.cols = ["path"]

            for line in db_resp[[*args.cols]].to_string(index=False, header=False).splitlines():
                if args.moved:
                    print(line.strip().replace(args.moved[0], "", 1))
                else:
                    print(line.strip())
            if args.moved:
                moved_media(args, db_resp[["path"]].values.tolist(), *args.moved)
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
                print(f"{len(db_resp)} media" + (f" (limited to {args.limit})" if args.limit else ""))
            summary = db_resp.sum(numeric_only=True)
            duration = summary.get("duration") or 0
            duration = human_time(duration)
            print("Total duration:", duration)


def override_sort(string):
    YEAR_MONTH = lambda var: f"cast(strftime('%Y%m', datetime({var}, 'unixepoch')) as int)"

    return (
        string.replace("month_created", YEAR_MONTH("time_created"))
        .replace("month_modified", YEAR_MONTH("time_modified"))
        .replace("random", "random()")
        .replace("priority", "play_count, ntile(1000) over (order by size/duration) desc")
    )
