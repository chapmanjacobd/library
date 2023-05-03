import csv, operator, os, platform, re, shutil, socket, subprocess
from copy import deepcopy
from io import StringIO
from numbers import Number
from pathlib import Path
from platform import system
from random import randrange
from shlex import join, quote, split
from shutil import which
from time import sleep
from typing import Dict, List, Optional, Tuple, Union

from tabulate import tabulate

from xklb import consts, utils
from xklb.consts import SC
from xklb.scripts import process_bigdirs
from xklb.utils import cmd, cmd_interactive, human_time, log

try:
    import tkinter  # noqa

    from xklb import gui
except ModuleNotFoundError:
    gui = None


def generic_player(args) -> List[str]:
    if platform.system() == "Linux":
        player = ["xdg-open"]
    elif any(p in platform.system() for p in ("Windows", "_NT-", "MSYS")):
        player = ["cygstart"] if shutil.which("cygstart") else ["start", ""]
    else:
        player = ["open"]
    args.player_need_sleep = True
    return player


def calculate_duration(args, m) -> Tuple[int, int]:
    start = 0
    end = m.get("duration", 0)
    minimum_duration = 7 * 60

    if args.start:
        playhead = m.get("playhead")

        if args.start.isnumeric() and int(args.start) > 0:
            start = int(args.start)
        elif playhead and any([end == 0, end > minimum_duration]):
            start = playhead
        elif args.start == "wadsworth":
            start = m["duration"] * 0.3
        else:
            start = int(args.start)
    if args.end:
        if args.end == "dawsworth":
            end = m["duration"] * 0.65
        elif "+" in args.end:
            end = int(args.start) + int(args.end)
        else:
            end = int(args.end)

    return start, end


def get_browser() -> Optional[str]:
    default_application = cmd("xdg-mime", "query", "default", "text/html").stdout
    return which(default_application.replace(".desktop", ""))


def find_xdg_application(media_file) -> Optional[str]:
    if media_file.startswith("http"):
        return get_browser()

    mimetype = cmd("xdg-mime", "query", "filetype", media_file).stdout
    default_application = cmd("xdg-mime", "query", "default", mimetype).stdout
    return which(default_application.replace(".desktop", ""))


def parse(args, m) -> List[str]:
    player = generic_player(args)
    mpv = which("mpv.com") or which("mpv") or "mpv"

    if args.override_player:
        player = args.override_player
        args.player_need_sleep = False

    elif args.action in (SC.read) and m["path"]:
        player_path = find_xdg_application(m["path"])
        if player_path:
            args.player_need_sleep = False
            player = [player_path]

    elif mpv:
        args.player_need_sleep = False
        player = [mpv]
        if args.action in (SC.listen):
            player.extend([f"--input-ipc-server={args.mpv_socket}", "--no-video", "--keep-open=no", "--really-quiet"])
        elif args.action in (SC.watch):
            player.extend(["--force-window=yes", "--really-quiet"])

        if m["path"] and m["path"].startswith("http"):
            player.extend(["--script-opts=ytdl_hook-try_ytdl_first=yes"])

        if not args.multiple_playback:
            player.extend(["--fs"])

        if args.loop:
            player.extend(["--loop-file=inf"])

        if args.crop:
            player.extend(["--panscan=1.0"])

        if args.action in (SC.watch, SC.listen) and m:
            start, end = calculate_duration(args, m)
            if end != 0:
                if start != 0:
                    player.extend([f"--start={start}", "--no-save-position-on-quit"])
                if end != m["duration"]:
                    player.extend([f"--end={end}"])

        if args.action == SC.watch and m and m.get("subtitle_count") is not None:
            if m["subtitle_count"] > 0:
                player.extend(args.player_args_sub)
            elif m["size"] > 500 * 1000000:  # 500 MB
                log.debug("Skipping subs player_args: size")
            elif m.get("time_partial_first"):
                log.debug("Skipping subs player_args: partially watched")
            else:
                player.extend(args.player_args_no_sub)

    elif system() == "Linux":
        player_path = find_xdg_application(m["path"])
        if player_path:
            args.player_need_sleep = False
            player = [player_path]

    log.debug("player: %s", player)
    return player


def mv_to_keep_folder(args, media_file: str) -> None:
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
    if args.keep_cmd:
        utils.cmd_detach(split(args.keep_cmd), new_path)
    with args.db.conn:
        args.db.conn.execute("UPDATE media set path = ? where path = ?", [new_path, media_file])


def moved_media(args, moved_files: Union[str, list], base_from, base_to) -> int:
    moved_files = utils.conform(moved_files)
    modified_row_count = 0
    if moved_files:
        df_chunked = utils.chunks(moved_files, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""UPDATE media
                    SET path=REPLACE(path, '{quote(base_from)}', '{quote(base_to)}')
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def set_playhead(args, path: str, playhead: int) -> int:
    with args.db.conn:
        cursor = args.db.conn.execute(
            """UPDATE media
            SET playhead = :playhead
            WHERE path = :path
            """,
            {"playhead": playhead, "path": path},
        )
        return cursor.rowcount


def mark_media_watched(args, files) -> int:
    files = utils.conform(files)
    modified_row_count = 0
    if files:
        df_chunked = utils.chunks(files, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    """UPDATE media
                    SET play_count = play_count + 1
                    , time_played = cast(STRFTIME('%s') as int)
                    WHERE path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def mark_media_deleted(args, paths, time_deleted=consts.APPLICATION_START) -> int:
    paths = utils.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = utils.chunks(paths, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""update media
                    set time_deleted={time_deleted}
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def mark_media_undeleted(args, paths) -> int:
    return mark_media_deleted(args, paths, time_deleted=0)


def mark_media_deleted_like(args, paths) -> int:
    paths = utils.conform(paths)

    modified_row_count = 0
    if paths:
        for p in paths:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""update media
                    set time_deleted={consts.APPLICATION_START}
                    where path like ?""",
                    [p + "%"],
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def delete_media(args, paths) -> int:
    paths = utils.conform(paths)
    for p in paths:
        if args.prefix:
            Path(p).unlink(missing_ok=True)
        else:
            utils.trash(p)

    return mark_media_deleted(args, paths)


def delete_playlists(args, playlists) -> None:
    with args.db.conn:
        playlist_paths = playlists + [p.rstrip(os.sep) for p in playlists]
        args.db.conn.execute(
            "delete from playlists where path in (" + ",".join(["?"] * len(playlist_paths)) + ")",
            playlist_paths,
        )

    online_media = [p for p in playlists if p.startswith("http")]
    if online_media:
        with args.db.conn:
            args.db.conn.execute(
                "delete from media where playlist_path in (" + ",".join(["?"] * len(online_media)) + ")",
                (*online_media,),
            )

    local_media = [p.rstrip(os.sep) for p in playlists if not p.startswith("http")]
    for folder in local_media:
        with args.db.conn:
            args.db.conn.execute("delete from media where path like ?", (folder + "%",))


class Action:
    KEEP = "keep"
    DELETE = "delete"
    DELETE_IF_AUDIOBOOK = "delete_if_audiobook"
    SOFTDELETE = "softdelete"
    MOVE = "move"


class AskAction:
    ASK_KEEP = (Action.KEEP, Action.DELETE)
    ASK_MOVE = (Action.MOVE, Action.KEEP)
    ASK_DELETE = (Action.DELETE, Action.KEEP)
    ASK_SOFTDELETE = (Action.SOFTDELETE, Action.KEEP)
    ASK_MOVE_OR_DELETE = (Action.MOVE, Action.DELETE)


def post_act(args, media_file: str, action: Optional[str] = None, geom_data=None, media=None) -> None:
    mark_media_watched(args, [media_file])

    def handle_delete_action():
        if media_file.startswith("http"):
            mark_media_deleted(args, media_file)
        else:
            delete_media(args, media_file)

    def handle_soft_delete_action():
        mark_media_deleted(args, media_file)

    def handle_move_action():
        if not media_file.startswith("http"):
            mv_to_keep_folder(args, media_file)

    def handle_ask_action(ask_action: str):
        true_action, false_action = getattr(AskAction, ask_action)
        if gui and args.gui:
            response = gui.askkeep(
                media_file,
                len(media or []),
                geom_data,
                true_action=true_action,
                false_action=false_action,
            )
        else:
            response = utils.confirm(true_action.title() + "?")
        post_act(args, media_file, action=true_action if response else false_action)

    action = action or args.post_action

    if action == Action.KEEP:
        pass
    elif action == Action.DELETE:
        handle_delete_action()
    elif action == Action.DELETE_IF_AUDIOBOOK:
        if "audiobook" in media_file.lower():
            handle_delete_action()
    elif action == Action.SOFTDELETE:
        handle_soft_delete_action()
    elif action == Action.MOVE:
        handle_move_action()
    elif action.startswith("ask_"):
        handle_ask_action(action)
    else:
        raise ValueError("Unrecognized action:", action)


def override_sort(sort_expression: str) -> str:
    def year_month_sql(var):
        return f"cast(strftime('%Y%m', datetime({var}, 'unixepoch')) as int)"

    return (
        sort_expression.replace("month_created", year_month_sql("time_created"))
        .replace("month_modified", year_month_sql("time_modified"))
        .replace("random", "random()")
        .replace("priority", "ntile(1000) over (order by size) desc, duration")
    )


def last_chars(candidate) -> str:
    remove_groups = re.split(r"([\W]+|\s+|Ep\d+|x\d+|\.\d+)", candidate)
    log.debug(remove_groups)

    remove_chars = ""
    number_of_groups = 1
    while len(remove_chars) < 1:
        remove_chars += remove_groups[-number_of_groups]
        number_of_groups += 1

    return remove_chars


def get_ordinal_media(args, m: Dict) -> Dict:
    # TODO: maybe try https://dba.stackexchange.com/questions/43415/algorithm-for-finding-the-longest-prefix

    columns = args.db["media"].columns_dict

    total_media = args.db.execute("select count(*) val from media").fetchone()[0]
    candidate = deepcopy(m["path"])
    similar_videos = []
    while len(similar_videos) <= 1:
        if candidate == "":
            return m

        remove_chars = last_chars(candidate)

        new_candidate = candidate[: -len(remove_chars)]
        log.debug(f"Matches for '{new_candidate}':")

        if candidate in ("" or new_candidate):
            return m

        candidate = new_candidate
        query = f"""SELECT path FROM {'media' if args.play_in_order >= consts.SIMILAR_NO_FILTER_NO_FTS else args.table}
            WHERE 1=1
                and path like :candidate
                {'and COALESCE(time_deleted,0) = 0' if 'time_deleted' in columns else ''}
                {'' if args.play_in_order >= consts.SIMILAR_NO_FILTER else (" ".join(args.filter_sql) or '')}
            ORDER BY play_count, path
            LIMIT 1000
            """
        bindings = {"candidate": candidate + "%"}
        if args.play_in_order == consts.SIMILAR:
            if args.include or args.exclude:
                bindings = {**bindings, "query": args.filter_bindings["query"]}
        else:
            bindings = {**bindings, **args.filter_bindings}

        similar_videos = list(args.db.query(query, bindings))
        log.debug(similar_videos)

        TOO_MANY_SIMILAR = 99
        if len(similar_videos) > TOO_MANY_SIMILAR or len(similar_videos) == total_media:
            return m

        commonprefix = os.path.commonprefix([d["path"] for d in similar_videos])
        log.debug(commonprefix)
        PREFIX_LENGTH_THRESHOLD = 3
        if len(Path(commonprefix).name) < PREFIX_LENGTH_THRESHOLD:
            log.debug("Using commonprefix")
            return m

    return similar_videos[0]


def watch_chromecast(args, m: dict, subtitles_file=None) -> Optional[subprocess.CompletedProcess]:
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
        if args.action in (SC.watch, SC.listen):
            catt_log = cmd(
                "catt",
                "-d",
                args.chromecast_device,
                "cast",
                "-s",
                subtitles_file if subtitles_file else consts.FAKE_SUBTITLE,
                m["path"],
            )
        else:
            catt_log = args.cc.play_url(m["path"], resolve=True, block=True)
    return catt_log


def listen_chromecast(args, m: dict) -> Optional[subprocess.CompletedProcess]:
    Path(consts.CAST_NOW_PLAYING).write_text(m["path"])
    Path(consts.FAKE_SUBTITLE).touch()
    catt = which("catt") or "catt"
    if args.cast_with_local:
        cast_process = subprocess.Popen(
            [catt, "-d", args.chromecast_device, "cast", "-s", consts.FAKE_SUBTITLE, m["path"]],
            **utils.os_bg_kwargs(),
        )
        sleep(0.974)  # imperfect lazy sync; I use keyboard shortcuts to send `set speed` commands to mpv for resync
        # if pyChromecast provides a way to sync accurately that would be very interesting to know; I have not researched it
        cmd_interactive(*args.player, "--", m["path"])
        catt_log = utils.Pclose(cast_process)  # wait for chromecast to stop (you can tell any chromecast to pause)
        sleep(3.0)  # give chromecast some time to breathe
    else:
        if m["path"].startswith("http"):
            catt_log = args.cc.play_url(m["path"], resolve=True, block=True)
        else:  #  local file
            catt_log = cmd(catt, "-d", args.chromecast_device, "cast", "-s", consts.FAKE_SUBTITLE, m["path"])

    return catt_log


def socket_play(args, m: dict) -> None:
    mpv = which("mpv") or "mpv"
    if args.sock is None:
        subprocess.Popen([mpv, "--idle", "--input-ipc-server=" + args.mpv_socket])
        while not Path(args.mpv_socket).exists():
            sleep(0.2)
        args.sock = socket.socket(socket.AF_UNIX)
        args.sock.connect(args.mpv_socket)

    start, end = calculate_duration(args, m)

    try:
        start = randrange(int(start), int(end - args.interdimensional_cable + 1))
        end = start + args.interdimensional_cable
    except Exception as e:
        log.info(e)
    if end == 0:
        return

    play_opts = f"start={start},save-position-on-quit=no"
    if args.action in (SC.listen):
        play_opts += ",video=no,really-quiet=yes"
    elif args.action in (SC.watch):
        play_opts += ",fullscreen=yes,force-window=yes,really-quiet=yes"

    if m["path"].startswith("http"):
        play_opts += ",script-opts=ytdl_hook-try_ytdl_first=yes"

    f = m["path"].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    args.sock.send((f'raw loadfile "{f}" replace "{play_opts}" \n').encode())
    sleep(args.interdimensional_cable)


def geom_walk(display, v=1, h=1) -> List[List[int]]:
    va = display.width // v
    ha = display.height // h

    geoms = []
    for v_idx in range(v):
        for h_idx in range(h):
            x = int(va * v_idx)
            y = int(ha * h_idx)
            log.debug("geom_walk %s", {"va": va, "ha": ha, "v_idx": v_idx, "h_idx": h_idx, "x": x, "y": y})
            geoms.append([va, ha, x, y])

    return geoms


def grid_stack(display, qty, swap=False) -> List[Tuple]:
    if qty == 1:
        return [("--fs", f'--screen-name="{display.name}"', f'--fs-screen-name="{display.name}"')]
    else:
        dv = list(utils.divisor_gen(qty))
        if not dv:
            vh = (qty, 1)
            log.debug("not dv %s", {"dv": dv, "vh": vh})
        else:
            v = dv[len(dv) // 2]
            h = qty // v
            vh = (v, h)
            log.debug("dv %s", {"dv": dv, "vh": vh})

    v, h = vh
    if swap:
        h, v = v, h
    holes = geom_walk(display, v=v, h=h)
    return [(hole, f'--screen-name="{display.name}"') for hole in holes]


def get_display_by_name(displays, screen_name):  # noqa: ANN201; -> List[screeninfo.Monitor]
    for d in displays:
        if d.name == screen_name:
            return [d]

    display_names = '", "'.join([d.name for d in displays])
    msg = f'Display "{screen_name}" not found. I see: "{display_names}"'
    raise ValueError(msg)


def is_hstack(args, display) -> bool:
    if args.hstack or args.portrait:
        return True
    elif args.vstack:
        return False
    elif display.width > display.height:  # wide
        return False
    else:  # tall or square: prefer horizontal split
        return True


def get_multiple_player_template(args) -> List[str]:
    import screeninfo

    displays = screeninfo.get_monitors()
    if args.screen_name:
        displays = get_display_by_name(displays, args.screen_name)

    if args.multiple_playback == consts.DEFAULT_MULTIPLE_PLAYBACK and len(displays) == 1:
        args.multiple_playback = 2
    elif args.multiple_playback == consts.DEFAULT_MULTIPLE_PLAYBACK and len(displays) > 1:
        args.multiple_playback = len(displays)
    elif args.multiple_playback < len(displays):
        # play videos on supporting screens but not active one
        displays = [d for d in displays if not d.is_primary]
        displays = displays[: len(args.multiple_playback)]

    min_media_per_screen, remainder = divmod(args.multiple_playback, len(displays))

    displays.sort(key=lambda d: d.width * d.height, reverse=True)
    players = []
    for d_idx, display in enumerate(displays):
        qty = min_media_per_screen
        if remainder > 0 and d_idx == 0:
            qty += remainder

        players.extend(grid_stack(display, qty, swap=is_hstack(args, display)))

    log.debug(players)

    return players


def geom(x_size, y_size, x, y) -> str:
    return f"--geometry={x_size}x{y_size}+{x}+{y}"


def _create_player(args, window_geometry, media):
    m = media.pop()
    print(m["path"])
    mp_args = ["--window-scale=1", "--no-border", "--no-keepaspect-window"]
    return {
        **m,
        "process": subprocess.Popen(
            [*args.player, *mp_args, *window_geometry, "--", m["path"]],
            **utils.os_bg_kwargs(),
        ),
    }


def multiple_player(args, media) -> None:
    args.player = parse(args, media[0])

    template = get_multiple_player_template(args)
    players = []

    media.reverse()  # because I use media.pop()
    try:
        while media or players:
            for t_idx, t in enumerate(template):
                SINGLE_PLAYBACK = ("--fs", '--screen-name="eDP"', '--fs-screen-name="eDP"')
                if len(t) == len(SINGLE_PLAYBACK):
                    player_hole = t
                    geom_data = None
                else:  # MULTI_PLAYBACK = ([640, 1080, 0, 0], '--screen-name="eDP"')
                    geom_data, screen_name = t
                    player_hole = [geom(*geom_data), screen_name]

                try:
                    m = players[t_idx]
                except IndexError:
                    log.debug("%s IndexError", t_idx)
                    if media:
                        players.append(_create_player(args, player_hole, media))
                else:
                    log.debug("%s Check if still running", t_idx)
                    if m["process"].poll() is not None:
                        r = utils.Pclose(m["process"])
                        if r.returncode != 0:
                            log.warning("Player exited with code %s", r.returncode)
                            log.debug(join(r.args))
                            if not args.ignore_errors:
                                raise SystemExit(r.returncode)

                        post_act(args, m["path"], geom_data=geom_data, media=media)

                        if media:
                            players[t_idx] = _create_player(args, player_hole, media)
                        else:
                            del players[t_idx]

            log.debug("%s media", len(media))
            sleep(0.2)  # I don't know if this is necessary but may as well~~
    finally:
        for m in players:
            m["process"].kill()


def local_player(args, m) -> subprocess.CompletedProcess:
    if system() == "Windows" or args.action in (SC.watch):
        r = cmd(*args.player, m["path"], strict=False)
    else:  # args.action in (SC.listen)
        r = cmd_interactive(*args.player, m["path"])

    if args.player_need_sleep:
        if hasattr(m, "duration"):
            delay = m["duration"]
        else:
            delay = 10  # TODO: idk
        sleep(delay)

    return r


def media_printer(args, media) -> None:
    if "b" in args.print:
        media = process_bigdirs(args, media)

    if args.verbose >= consts.LOG_DEBUG and args.cols and "*" in args.cols:
        breakpoint()

    if not media:
        utils.no_media_found()

    if "a" in args.print:
        D = {"path": "Aggregate", "count": len(media)}

        if "duration" in media[0]:
            D["duration"] = sum((d["duration"] or 0) for d in media)
            D["avg_duration"] = sum((d["duration"] or 0) for d in media) / len(media)

        if "sparseness" in media[0]:
            D["sparseness"] = None

        if "size" in media[0]:
            D["size"] = sum((d["size"] or 0) for d in media)
            D["avg_size"] = sum((d["size"] or 0) for d in media) / len(media)

        if args.cols:
            for c in args.cols:
                if isinstance(media[0][c], Number):
                    D[f"sum_{c}"] = sum((d[c] or 0) for d in media)
                    D[f"avg_{c}"] = sum((d[c] or 0) for d in media) / len(media)
        media = [D]

    else:
        if "d" in args.print:
            marked = mark_media_deleted(args, list(map(operator.itemgetter("path"), media)))
            log.warning(f"Marked {marked} metadata records as deleted")
        if "w" in args.print:
            marked = mark_media_watched(args, list(map(operator.itemgetter("path"), media)))
            log.warning(f"Marked {marked} metadata records as watched")

    if "f" in args.print:
        if args.limit == 1:
            f = media[0]["path"]
            if not Path(f).exists():
                mark_media_deleted(args, f)
                raise FileNotFoundError
            utils.pipe_print(quote(f))
            return
        else:
            if not args.cols:
                args.cols = ["path"]

            selected_cols = [{k: d.get(k, None) for k in args.cols} for d in media]
            virtual_csv = StringIO()
            wr = csv.writer(virtual_csv, quoting=csv.QUOTE_NONE)
            wr = csv.DictWriter(virtual_csv, fieldnames=args.cols)
            wr.writerows(selected_cols)

            virtual_csv.seek(0)
            for line in virtual_csv.readlines():
                if args.moved:
                    utils.pipe_print(line.strip().replace(args.moved[0], "", 1))
                else:
                    utils.pipe_print(line.strip())
            if args.moved:
                moved_media(args, list(map(operator.itemgetter("path"), media)), *args.moved)
                return
            return
    else:
        tbl = deepcopy(media)
        utils.col_resize(tbl, "path", 22)
        utils.col_resize(tbl, "title", 11)

        utils.col_naturalsize(tbl, "size")
        utils.col_naturalsize(tbl, "avg_size")
        utils.col_duration(tbl, "duration")
        utils.col_duration(tbl, "avg_duration")

        for t in consts.TIME_COLUMNS:
            utils.col_naturaldate(tbl, t)

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))

        if len(media) > 1:
            print(f"{len(media)} media" + (f" (limited to {args.limit})" if args.limit else ""))

        duration = sum(m.get("duration") or 0 for m in media)
        if duration > 0:
            duration = human_time(duration)
            if "a" not in args.print:
                print("Total duration:", duration)
                return
            return
        return


def printer(args, query, bindings) -> None:
    media = list(args.db.query(query, bindings))
    try:
        media_printer(args, media)
    except FileNotFoundError:
        return printer(args, query, bindings)  # try again to find a valid file
