import csv, json, os, platform, re, shutil, socket, statistics, subprocess, sys
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

from xklb import consts, db, history, media, utils
from xklb.consts import SC
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
    playhead = m.get("playhead")
    if playhead:
        start = playhead

    duration = m.get("duration", 20 * 60)
    if args.start:
        if args.start.isnumeric() and int(args.start) > 0:
            start = int(args.start)
        elif "%" in args.start:
            start_percent = int(args.start[:-1])
            start = int(duration * start_percent / 100)
        elif playhead and any([end == 0, end > minimum_duration]):
            start = playhead
        elif args.start == "wadsworth":
            start = duration * 0.3
        else:
            start = int(args.start)
    if args.end:
        if args.end == "dawsworth":
            end = duration * 0.65
        elif "%" in args.end:
            end_percent = int(args.end[:-1])
            end = int(duration * end_percent / 100)
        elif "+" in args.end:
            end = int(args.start) + int(args.end)
        else:
            end = int(args.end)

    log.debug("calculate_duration: %s -- %s", start, end)
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

        if getattr(args, "multiple_playback", 1) < 2:
            player.extend(["--fs"])

        if args.loop:
            player.extend(["--loop-file=inf"])

        if getattr(args, "crop", None):
            player.extend(["--panscan=1.0"])

        if args.action in (SC.watch, SC.listen, SC.search) and m:
            start, end = calculate_duration(args, m)
            if end != 0:
                if start != 0:
                    player.extend([f"--start={start}"])
                    if args.start:
                        player.extend(["--no-save-position-on-quit"])
                if end != m["duration"]:
                    player.extend([f"--end={end}"])

        if args.action == SC.watch and m and m.get("subtitle_count") is not None:
            if m["subtitle_count"] > 0:
                player.extend(args.player_args_sub)
            elif m["size"] > 500 * 1000000:  # 500 MB
                log.debug("Skipping subs player_args: size")
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


def mark_download_attempt(args, paths) -> int:
    paths = utils.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = utils.chunks(paths, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""update media
                    set time_modified={consts.now()}
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def mark_media_deleted(args, paths) -> int:
    paths = utils.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = utils.chunks(paths, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    f"""update media
                    set time_deleted={consts.APPLICATION_START}
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def mark_media_undeleted(args, paths) -> int:
    paths = utils.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = utils.chunks(paths, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    """update media
                    set time_deleted=0
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


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
        if p.startswith("http"):
            continue

        if getattr(args, "prefix", False):
            Path(p).unlink(missing_ok=True)
        else:
            utils.trash(p, detach=len(paths) < 30)

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
                """DELETE from media where
                playlist_id in (
                    SELECT id from playlists
                    WHERE path IN ("""
                + ",".join(["?"] * len(online_media))
                + "))",
                (*online_media,),
            )

    local_media = [p.rstrip(os.sep) for p in playlists if not p.startswith("http")]
    for folder in local_media:
        with args.db.conn:
            args.db.conn.execute("delete from media where path like ?", (folder + "%",))


class Action:
    KEEP = "KEEP"
    DELETE = "DELETE"
    DELETE_IF_AUDIOBOOK = "DELETE_IF_AUDIOBOOK"
    SOFTDELETE = "SOFTDELETE"
    MOVE = "MOVE"


class AskAction:
    ASK_KEEP = (Action.KEEP, Action.DELETE)
    ASK_MOVE = (Action.MOVE, Action.KEEP)
    ASK_DELETE = (Action.DELETE, Action.KEEP)
    ASK_SOFTDELETE = (Action.SOFTDELETE, Action.KEEP)
    ASK_MOVE_OR_DELETE = (Action.MOVE, Action.DELETE)


def post_act(args, media_file: str, action: Optional[str] = None, geom_data=None, media_len=0) -> None:
    history.add(args, [media_file], mark_done=True)

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
                media_len,
                geom_data,
                true_action=true_action,
                false_action=false_action,
            )
        else:
            response = utils.confirm(true_action.title() + "?")
        post_act(args, media_file, action=true_action if response else false_action)  # answer the question

    action = action or args.post_action
    action = action.upper()

    if action == "NONE":
        action = Action.KEEP

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
    elif action.startswith("ASK_"):
        handle_ask_action(action)
    else:
        raise ValueError("Unrecognized action:", action)


def override_sort(sort_expression: str) -> str:
    def year_month_sql(var):
        return f"cast(strftime('%Y%m', datetime({var}, 'unixepoch')) as int)"

    def year_month_day_sql(var):
        return f"cast(strftime('%Y%m%d', datetime({var}, 'unixepoch')) as int)"

    return (
        sort_expression.replace("month_created", year_month_sql("time_created"))
        .replace("month_modified", year_month_sql("time_modified"))
        .replace("date_created", year_month_day_sql("time_created"))
        .replace("date_modified", year_month_day_sql("time_modified"))
        .replace("random()", "random")
        .replace("random", "random()")
        .replace("priority", "ntile(1000) over (order by size) desc, duration")
    )


def filter_args_sql(args, m_columns):
    return f"""
        {'and path like "http%"' if getattr(args, 'safe', False) else ''}
        {f'and path not like "{args.keep_dir}%"' if getattr(args, 'keep_dir', False) and Path(args.keep_dir).exists() else ''}
        {'and COALESCE(time_deleted,0) = 0' if 'time_deleted' in m_columns and 'time_deleted' not in ' '.join(sys.argv) else ''}
        {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
        {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
        {'AND COALESCE(time_downloaded,0) = 0' if args.online_media_only else ''}
        {'AND COALESCE(time_downloaded,1)!= 0 AND path not like "http%"' if args.local_media_only else ''}
    """


def last_chars(candidate) -> str:
    remove_groups = re.split(r"([\W]+|\s+|Ep\d+|x\d+|\.\d+)", candidate)
    log.debug(remove_groups)

    remove_chars = ""
    number_of_groups = 1
    while len(remove_chars) < 1:
        remove_chars += remove_groups[-number_of_groups]
        number_of_groups += 1

    return remove_chars


def get_ordinal_media(args, m: Dict, ignore_paths=None) -> Dict:
    # TODO: maybe try https://dba.stackexchange.com/questions/43415/algorithm-for-finding-the-longest-prefix
    if ignore_paths is None:
        ignore_paths = []

    m_columns = db.columns(args, "media")

    cols = args.cols or ["path", "title", "duration", "size", "subtitle_count", "is_dir"]
    args.select_sql = "\n        , ".join([c for c in cols if c in m_columns or c in ["*"]])

    total_media = args.db.execute("select count(*) val from media").fetchone()[0]
    candidate = deepcopy(m["path"])
    if args.play_in_order >= consts.SIMILAR_NO_FILTER_NO_FTS_PARENT:
        candidate = str(Path(candidate).parent)

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
        query = f"""WITH m as (
                SELECT
                    SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                    , MIN(h.time_played) time_first_played
                    , MAX(h.time_played) time_last_played
                    , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                    , {args.select_sql}
                FROM media m
                LEFT JOIN history h on h.media_id = m.id
                WHERE 1=1
                    AND COALESCE(time_deleted, 0)=0
                    and path like :candidate
                    {'' if args.play_in_order >= consts.SIMILAR_NO_FILTER_NO_FTS else f'and m.id in (select id from {args.table})'}
                    {filter_args_sql(args, m_columns)}
                    {'' if args.play_in_order >= consts.SIMILAR_NO_FILTER else (" ".join(args.filter_sql) or '')}
                    {"and path not in ({})".format(",".join([f":ignore_path{i}" for i in range(len(ignore_paths))])) if len(ignore_paths) > 0 else ''}
                GROUP BY m.id, m.path
            )
            SELECT
                *
            FROM m
            ORDER BY play_count, path
            LIMIT 1000
            """

        ignore_path_params = {f"ignore_path{i}": value for i, value in enumerate(ignore_paths)}
        bindings = {"candidate": candidate + "%", **ignore_path_params}
        if args.play_in_order >= consts.SIMILAR_NO_FILTER:
            if args.include or args.exclude:
                bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("FTS")}}
        else:
            bindings = {**bindings, **args.filter_bindings}

        similar_videos = list(args.db.query(query, bindings))
        log.debug(similar_videos)

        TOO_MANY_SIMILAR = 99
        if len(similar_videos) > TOO_MANY_SIMILAR or len(similar_videos) == total_media:
            return m

        if len(similar_videos) > 1:
            commonprefix = os.path.commonprefix([d["path"] for d in similar_videos])
            log.debug(commonprefix)
            PREFIX_LENGTH_THRESHOLD = 3
            if len(Path(commonprefix).name) < PREFIX_LENGTH_THRESHOLD:
                log.debug("Using commonprefix")
                return m

    return similar_videos[0]


def get_related_media(args, m: Dict) -> List[Dict]:
    m_columns = db.columns(args, "media")
    m_columns.update(rank=int)

    m = media.get(args, m["path"])
    words = set(
        utils.conform(utils.extract_words(m.get(k)) for k in m if k in db.config["media"]["search_columns"]),
    )
    args.include = sorted(words, key=len, reverse=True)[:100]
    args.table, search_bindings = db.fts_search_sql(
        "media",
        fts_table=args.db["media"].detect_fts(),
        include=args.include,
        exclude=args.exclude,
    )
    args.filter_bindings = {**args.filter_bindings, **search_bindings}

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , {args.select_sql}
                , rank
            FROM {args.table} m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                and path != :path
                {filter_args_sql(args, m_columns)}
                {'' if args.related >= consts.RELATED_NO_FILTER else (" ".join(args.filter_sql) or '')}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        ORDER BY play_count
            , m.path like "http%"
            , {'rank' if 'sort' in args.defaults else f'ntile(1000) over (order by rank), {args.sort}'}
            , path
        {"LIMIT " + str(args.limit - 1) if args.limit else ""} {args.offset_sql}
        """
    bindings = {"path": m["path"]}
    if args.related >= consts.RELATED_NO_FILTER:
        bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("FTS")}}
    else:
        bindings = {**bindings, **args.filter_bindings}

    related_videos = list(args.db.query(query, bindings))
    log.debug(related_videos)

    return [m, *related_videos]


def get_dir_media(args, dirs: List, include_subdirs=False) -> List[Dict]:
    if len(dirs) == 0:
        return utils.no_media_found()

    m_columns = db.columns(args, "media")

    if include_subdirs:
        filter_paths = "AND (" + " OR ".join([f"path LIKE :subpath{i}" for i in range(len(dirs))]) + ")"
    else:
        filter_paths = (
            "AND ("
            + " OR ".join([f"(path LIKE :subpath{i} and path not like :subpath{i} || '/%')" for i in range(len(dirs))])
            + ")"
        )

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , {args.select_sql}
            FROM media m
            LEFT JOIN history h on h.media_id = m.id
            WHERE 1=1
                AND COALESCE(time_deleted, 0)=0
                and m.id in (select id from {args.table})
                {filter_args_sql(args, m_columns)}
                {filter_paths}
                {'' if args.related >= consts.DIRS_NO_FILTER else (" ".join(args.filter_sql) or '')}
            GROUP BY m.id, m.path
        )
        SELECT *
        FROM m
        ORDER BY play_count
            , m.path LIKE "http%"
            {'' if 'sort' in args.defaults else ', ' + args.sort}
            , path
        {"LIMIT 10000" if 'limit' in args.defaults else str(args.limit)} {args.offset_sql}
    """
    subpath_params = {f"subpath{i}": value + "%" for i, value in enumerate(dirs)}

    bindings = {**subpath_params}
    if args.related >= consts.DIRS_NO_FILTER:
        bindings = {**bindings, **{k: v for k, v in args.filter_bindings.items() if k.startswith("FTS")}}
    else:
        bindings = {**bindings, **args.filter_bindings}

    subpath_videos = list(args.db.query(query, bindings))
    log.debug(subpath_videos)
    log.info("len(subpath_videos) = %s", len(subpath_videos))

    return subpath_videos


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

    play_opts = f"start={start},save-position-on-quit=no,resume-playback=no"
    if args.action in (SC.listen):
        play_opts += ",video=no"
    elif args.action in (SC.watch):
        play_opts += ",fullscreen=yes,force-window=yes"

    if m["path"].startswith("http"):
        play_opts += ",script-opts=ytdl_hook-try_ytdl_first=yes"
    else:
        play_opts += ",really-quiet=yes"

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


def modify_display_size_for_taskbar(display):
    try:
        if platform.system() == "Windows":
            import win32gui  # type: ignore

            taskbar_window_handle = win32gui.FindWindow("Shell_TrayWnd", None)
            if taskbar_window_handle == 0:
                taskbar_window_handle = win32gui.FindWindow("Shell_SecondaryTrayWnd", None)
            if taskbar_window_handle == 0:
                return display

            work_area = win32gui.GetMonitorInfo(taskbar_window_handle)["rcWork"]  # type: ignore

            _taskbar_height = display.height - work_area[3]
            display.height = work_area[3] - work_area[1]
            display.width = work_area[2] - work_area[0]

        elif platform.system() == "Linux":
            xprop_output = subprocess.check_output("xprop -root _NET_WORKAREA".split()).decode().strip()
            work_area = [int(x) for x in xprop_output.split(" = ")[1].split(",")]

            _taskbar_height = display.height - work_area[3]
            display.height = work_area[3] - work_area[1]
            display.width = work_area[2] - work_area[0]

        elif platform.system() == "Darwin":
            dock_height = int(subprocess.check_output(["defaults", "read", "com.apple.dock", "tilesize"]).strip())
            dock_position = (
                subprocess.check_output(["defaults", "read", "com.apple.dock", "orientation"]).decode().strip()
            )
            if dock_position == "left" or dock_position == "right":
                display.width -= dock_height
            else:
                display.height -= dock_height

        return display
    except:
        return display


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

    if min_media_per_screen > 1:
        displays[0] = modify_display_size_for_taskbar(displays[0])

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

    media.reverse()  # because media.pop()
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

                        post_act(args, m["path"], geom_data=geom_data, media_len=len(media))

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
    if args.folder:
        paths = [str(Path(m["path"]).parent)]
    elif args.folder_glob:
        paths = utils.fast_glob(Path(m["path"]).parent, args.folder_glob)
    else:
        paths = [m["path"]]

    if system() == "Windows" or args.action in (SC.watch):
        r = cmd(*args.player, *paths, strict=False)
    else:  # args.action in (SC.listen)
        r = cmd_interactive(*args.player, *paths)

    if args.player_need_sleep:
        try:
            utils.confirm("Continue?")
        except Exception:
            if hasattr(m, "duration"):
                delay = m["duration"]
            else:
                delay = 10  # TODO: idk
            sleep(delay)

    return r


def frequency_time_to_sql(freq, time_column):
    if freq == "daily":
        freq_label = "day"
        freq_sql = f"strftime('%Y-%m-%d', datetime({time_column}, 'unixepoch'))"
    elif freq == "weekly":
        freq_label = "week"
        freq_sql = f"strftime('%Y-%W', datetime({time_column}, 'unixepoch'))"
    elif freq == "monthly":
        freq_label = "month"
        freq_sql = f"strftime('%Y-%m', datetime({time_column}, 'unixepoch'))"
    elif freq == "quarterly":
        freq_label = "quarter"
        freq_sql = f"strftime('%Y', datetime({time_column}, 'unixepoch', '-3 months')) || '-Q' || ((strftime('%m', datetime({time_column}, 'unixepoch', '-3 months')) - 1) / 3 + 1)"
    elif freq == "yearly":
        freq_label = "year"
        freq_sql = f"strftime('%Y', datetime({time_column}, 'unixepoch'))"
    elif freq == "decadally":
        freq_label = "decade"
        freq_sql = f"(CAST(strftime('%Y', datetime({time_column}, 'unixepoch')) AS INTEGER) / 10) * 10"
    elif freq == "hourly":
        freq_label = "hour"
        freq_sql = f"strftime('%Y-%m-%d %Hh', datetime({time_column}, 'unixepoch'))"
    elif freq == "minutely":
        freq_label = "minute"
        freq_sql = f"strftime('%Y-%m-%d %H:%M', datetime({time_column}, 'unixepoch'))"
    else:
        msg = f"Invalid value for 'freq': {freq}"
        raise ValueError(msg)
    return freq_label, freq_sql


def historical_usage(args, freq="monthly", time_column="time_played", where=""):
    freq_label, freq_sql = frequency_time_to_sql(freq, time_column)

    query = f"""WITH m as (
            SELECT
                SUM(CASE WHEN h.done = 1 THEN 1 ELSE 0 END) play_count
                , MIN(h.time_played) time_first_played
                , MAX(h.time_played) time_last_played
                , FIRST_VALUE(h.playhead) OVER (PARTITION BY h.media_id ORDER BY h.time_played DESC) playhead
                , *
            FROM media m
            JOIN history h on h.media_id = m.id
            WHERE 1=1
            {'' if time_column =="time_deleted" else "AND COALESCE(time_deleted, 0)=0"}
            GROUP BY m.id, m.path
        )
        SELECT
            {freq_sql} AS {freq_label}
            , SUM(duration) AS total_duration
            , AVG(duration) AS avg_duration
            , SUM(size) AS total_size
            , AVG(size) AS avg_size
            , count(*) as count
        FROM m
        WHERE {time_column}>0 {where}
        GROUP BY {freq_label}
    """
    return list(args.db.query(query))


def cadence_adjusted_duration(args, duration):
    history = historical_usage(args, freq="hourly")
    try:
        historical_hourly = statistics.mean((d["total_duration"] or 0) for d in history)
    except statistics.StatisticsError:
        try:
            historical_hourly = history[0]["total_duration"]
        except IndexError:
            return None

    return int(duration / historical_hourly * 60 * 60)


def historical_usage_items(args, freq="monthly", time_column="time_modified", where=""):
    m_columns = db.columns(args, "media")

    freq_label, freq_sql = frequency_time_to_sql(freq, time_column)
    query = f"""SELECT
            {freq_sql} AS {freq_label}
            {', SUM(duration) AS total_duration' if 'duration' in m_columns else ''}
            {', AVG(duration) AS avg_duration' if 'duration' in m_columns else ''}
            {', SUM(size) AS total_size' if 'size' in m_columns else ''}
            {', AVG(size) AS avg_size' if 'size' in m_columns else ''}
            , count(*) as count
        FROM media m
        WHERE coalesce({freq_label}, 0)>0
            and {time_column}>0 {where}
            {'' if time_column =="time_deleted" else "AND COALESCE(time_deleted, 0)=0"}
        GROUP BY {freq_label}
    """
    return list(args.db.query(query))


def cadence_adjusted_items(args, items: int):
    history = historical_usage_items(args, freq="minutely")
    try:
        historical_minutely = statistics.mean((d["count"] or 0) for d in history)
        log.debug("historical_minutely mean %s", historical_minutely)
    except statistics.StatisticsError:
        try:
            historical_minutely = history[0]["count"]
            log.debug("historical_minutely 1n %s", historical_minutely)
        except IndexError:
            log.debug("historical_minutely index error")
            return None

    log.debug("items %s", items)

    return int(items / historical_minutely * 60)


def filter_deleted(media):
    http_list = []
    local_list = []
    nonexistent_local_paths = []

    for i, m in enumerate(media):
        path = m["path"]
        if path.startswith("http"):
            http_list.append(m)
            continue

        if len(local_list) == 50 and len(nonexistent_local_paths) <= 2:
            return local_list + http_list + media[i:], nonexistent_local_paths

        if os.path.exists(path):
            local_list.append(m)
        else:
            nonexistent_local_paths.append(path)

    return local_list + http_list, nonexistent_local_paths


def media_printer(args, data, units=None, media_len=None) -> None:
    if units is None:
        units = "media"

    cols = getattr(args, "cols", [])

    media = deepcopy(data)

    if args.verbose >= consts.LOG_DEBUG and cols and "*" in cols:
        breakpoint()

    if not media:
        utils.no_media_found()

    if "f" not in args.print and "limit" in getattr(args, "defaults", []):
        media.reverse()

    duration = sum(m.get("duration") or 0 for m in media)
    if "a" in args.print and "Aggregate" not in getattr(media[0], "path", ""):
        if "count" in media[0]:
            D = {"path": "Aggregate", "count": sum(d["count"] for d in media)}
        elif args.action == SC.download_status and "never_downloaded" in media[0]:
            potential_downloads = sum(d["never_downloaded"] + d["retry_queued"] for d in media)
            D = {"path": "Aggregate", "count": potential_downloads}
        else:
            D = {"path": "Aggregate", "count": len(media)}

        if "duration" in media[0] and args.action not in (SC.download_status):
            D["duration"] = duration
            D["avg_duration"] = duration / len(media)

        if hasattr(args, "action"):
            if args.action in (SC.listen, SC.watch, SC.read, SC.view):
                D["cadence_adj_duration"] = cadence_adjusted_duration(args, duration)
            elif args.action in (SC.download, SC.download_status):
                D["download_duration"] = cadence_adjusted_items(args, D["count"])

        if "size" in media[0]:
            D["size"] = sum((d["size"] or 0) for d in media)
            D["avg_size"] = sum((d["size"] or 0) for d in media) / len(media)

        if cols:
            for c in cols:
                if isinstance(media[0][c], Number):
                    D[f"sum_{c}"] = sum((d[c] or 0) for d in media)
                    D[f"avg_{c}"] = sum((d[c] or 0) for d in media) / len(media)
        media = [D]

    else:
        if "r" in args.print:
            marked = mark_media_deleted(args, [d["path"] for d in media if not Path(d["path"]).exists()])
            log.warning(f"Marked {marked} metadata records as deleted")
        elif "d" in args.print:
            marked = mark_media_deleted(args, [d["path"] for d in media])
            log.warning(f"Marked {marked} metadata records as deleted")

        if "w" in args.print:
            marked = history.add(args, [d["path"] for d in media])
            log.warning(f"Marked {marked} metadata records as watched")

    if "a" not in args.print and args.action == SC.download_status:
        for m in media:
            m["download_duration"] = cadence_adjusted_items(
                args, m["never_downloaded"] + m["retry_queued"]
            )  # TODO where= p.extractor_key, or try to use SQL

    for k, v in list(media[0].items()):
        if k.endswith("size"):
            utils.col_naturalsize(media, k)
        elif k.endswith("duration") or k in ("playhead",):
            utils.col_duration(media, k)
        elif k.startswith("time_") or "_time_" in k:
            utils.col_naturaldate(media, k)
        elif k == "title_path":
            media = [{"title_path": "\n".join(utils.concat(d["title"], d["path"])), **d} for d in media]
            media = [{k: v for k, v in d.items() if k not in ("title", "path")} for d in media]
        elif k.startswith("percent") or k.endswith("ratio"):
            for d in media:
                d[k] = f"{d[k]:.2%}"
        # elif isinstance(v, (int, float)):
        #     for d in media:
        #         if d[k] is not None:
        #             d[k] = f'{d[k]:n}'  # TODO add locale comma separators

    def should_align_right(k, v):
        if k.endswith("size") or k.startswith("percent") or k.endswith("ratio"):
            return True
        if isinstance(v, (int, float)):
            return True

    media = utils.list_dict_filter_bool(media)

    if "f" in args.print:
        if len(media) <= 1000:
            media, deleted_paths = filter_deleted(media)
            mark_media_deleted(args, deleted_paths)
            if len(media) == 0:
                raise FileNotFoundError

        if not cols:
            cols = ["path"]

        selected_cols = [{k: d.get(k, None) for k in cols} for d in media]
        virtual_csv = StringIO()
        wr = csv.writer(virtual_csv, quoting=csv.QUOTE_NONE)
        wr = csv.DictWriter(virtual_csv, fieldnames=cols)
        wr.writerows(selected_cols)

        virtual_csv.seek(0)
        for line in virtual_csv.readlines():
            if getattr(args, "moved", False):
                utils.pipe_print(line.strip().replace(args.moved[0], "", 1))
            else:
                utils.pipe_print(line.strip())
        if args.moved:
            moved_media(args, [d["path"] for d in media], *args.moved)
    elif "j" in args.print or consts.MOBILE_TERMINAL:
        print(json.dumps(media, indent=3))
    elif "c" in args.print:
        utils.write_csv_to_stdout(media)
    else:
        tbl = deepcopy(media)
        tbl = [{k: f"{v:.4f}" if isinstance(v, float) else v for k, v in d.items()} for d in tbl]
        max_col_widths = utils.calculate_max_col_widths(tbl)
        adjusted_widths = utils.distribute_excess_width(max_col_widths)
        for k, v in adjusted_widths.items():
            utils.col_resize(tbl, k, v)

        colalign = ["right" if should_align_right(k, v) else "left" for k, v in tbl[0].items()]
        print(tabulate(tbl, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False, colalign=colalign))

        if len(media) > 1:
            print(
                f"{media_len or len(media)} {units}"
                + (f" (limited by --limit {args.limit})" if args.limit and int(args.limit) <= len(media) else "")
            )

        if duration > 0:
            duration = human_time(duration)
            if "a" not in args.print:
                print("Total duration:", duration)


def printer(args, query, bindings, units=None) -> None:
    media = list(args.db.query(query, bindings))
    try:
        media_printer(args, media, units=units)
    except FileNotFoundError:
        printer(args, query, bindings)  # try again to find a valid file
