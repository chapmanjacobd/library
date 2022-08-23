import argparse
import shlex
import shutil
import subprocess
from pathlib import Path

import ffmpeg
import pandas as pd
import sqlite_utils
from catt.api import CattDevice
from rich.prompt import Confirm

from xklb.db import sqlite_con
from xklb.utils import (
    CAST_NOW_PLAYING,
    DEFAULT_MPV_SOCKET,
    DEFAULT_PLAY_QUEUE,
    SC,
    cmd,
    filter_None,
    flatten,
    get_ip_of_chromecast,
    log,
    pkill,
)
from xklb.utils_player import (
    delete_media,
    get_ordinal_media,
    listen_chromecast,
    local_player,
    mark_media_deleted,
    mark_media_watched,
    mv_to_keep_folder,
    override_sort,
    printer,
    remove_media,
    socket_play,
    watch_chromecast,
)

idle_mpv = lambda args: ["mpv", "--idle", f"--input-ipc-server={args.mpv_socket}"]


def parse_args(action, default_db, default_chromecast=""):
    parser = argparse.ArgumentParser(prog="lb " + action, formatter_class=argparse.ArgumentDefaultsHelpFormatter)

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
    parser.add_argument(
        "--moved",
        nargs=2,
        help="""For use with `-p f` to specify files moved with rsync or a similar tool. For example:
rsync -a --info=progress2 --no-inc-recursive --remove-source-files --files-from=<(
    lt ~/lb/audio.db -w 'play_count = 0' -u random -L 1200 -p f \
    --moved /mnt/d/ /mnt/d/80_Now_Listening/
) /mnt/d/ /mnt/d/80_Now_Listening/

Notice how `--moved` mirrors the src/dest prefix syntax in rsync?""",
    )

    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a non-standard column when printing")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help="Set play queue size")
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
    parser.add_argument(
        "--keep-dir",
        "--keepdir",
        default="keep",
        help="Used with post-action askkeep. Files will move here after playing",
    )
    parser.add_argument("--shallow-organize", default="/mnt/d/")

    parser.add_argument("--db", "-db")
    parser.add_argument("--ignore-errors", "--ignoreerrors", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db

    if not args.limit and all([not args.print, args.action in [SC.listen, SC.watch, SC.tubelisten, SC.tubewatch]]):
        args.limit = DEFAULT_PLAY_QUEUE
    elif args.limit in ["inf", "all"]:
        args.limit = None

    if not args.sort and args.action in [SC.listen, SC.watch, SC.tubelisten, SC.tubewatch]:
        args.sort = ["priority"]
    if args.sort:
        args.sort = " ".join(args.sort)
        args.sort = override_sort(args.sort)

    if args.cols:
        args.cols = list(flatten([s.split(",") for s in args.cols]))

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
                size_rules += f"and size >= {abs(int(size_rule)) * B_TO_MB} "
            elif "-" in size_rule:
                # max size rule
                size_rules += f"and {abs(int(size_rule)) * B_TO_MB} >= size "
            else:
                # approximate size rule
                size_mb = float(size_rule) * B_TO_MB
                size_rules += f"and {size_mb + (size_mb /10)} >= size and size >= {size_mb - (size_mb /10)} "

        args.size = size_rules

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


def post_act(args, media_file: str):
    mark_media_watched(args, media_file)
    if args.post_action == "keep":
        return

    if args.action in [SC.tubelisten, SC.tubewatch]:
        if args.post_action == "remove":
            remove_media(args, media_file)
        elif args.post_action == "ask":
            if not Confirm.ask("Keep?", default=False):
                remove_media(args, media_file)  # only remove metadata
        else:
            raise Exception("Unrecognized post_action", args.post_action)

    if args.action in [SC.listen, SC.watch]:
        if args.post_action == "remove":
            remove_media(args, media_file)

        elif args.post_action == "delete":
            delete_media(args, media_file)

        elif args.post_action == "delete-if-audiobook":
            if "audiobook" in media_file.lower():
                delete_media(args, media_file)

        elif args.post_action == "ask":
            if not Confirm.ask("Keep?", default=False):
                delete_media(args, media_file)

        elif args.post_action == "askkeep":
            if not Confirm.ask("Keep?", default=False):
                delete_media(args, media_file)
            else:
                mv_to_keep_folder(args, media_file)

        else:
            raise Exception("Unrecognized post_action", args.post_action)


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


def chromecast_play(args, m):
    if args.action in [SC.watch, SC.tubewatch]:
        catt_log = watch_chromecast(args, m, subtitles_file=externalize_subtitle(m["path"]))
    elif args.action in [SC.listen, SC.tubelisten]:
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
                args.play_in_order > 1 and args.action not in [SC.listen, SC.tubelisten],
                args.play_in_order >= 1 and args.action == SC.listen and "audiobook" in media_file.lower(),
                args.play_in_order >= 1
                and args.action == SC.tubelisten
                and m["title"]
                and "audiobook" in m["title"].lower(),
            ]
        ):
            media_file = get_ordinal_media(args, media_file)

        if args.action in [SC.watch, SC.listen]:
            media_path = Path(args.prefix + media_file).resolve()
            if not media_path.exists():
                mark_media_deleted(args, media_file)
                continue
            media_file = str(media_path)

            if args.transcode:
                media_file = transcode(media_file)

        if args.action in [SC.watch, SC.tubewatch]:
            print(media_file)
        elif args.action == SC.listen:
            print(cmd("ffprobe", "-hide_banner", "-loglevel", "info", media_file).stderr)

        if args.chromecast:
            chromecast_play(args, m)

        elif args.interdimensional_cable:
            socket_play(args, m)

        else:
            local_player(args, m, media_file)

        if args.action in [SC.listen, SC.watch, SC.tubelisten, SC.tubewatch] and not args.interdimensional_cable:
            post_act(args, media_file)


audio_include_string = (
    lambda x: f"""and (
    path like :include{x}
    OR mood like :include{x}
    OR genre like :include{x}
    OR year like :include{x}
    OR bpm like :include{x}
    OR key like :include{x}
    OR time like :include{x}
    OR decade like :include{x}
    OR categories like :include{x}
    OR city like :include{x}
    OR country like :include{x}
    OR description like :include{x}
    OR album like :include{x}
    OR title like :include{x}
    OR artist like :include{x}
)"""
)

audio_exclude_string = (
    lambda x: f"""and (
    path not like :exclude{x}
    AND mood not like :exclude{x}
    AND genre not like :exclude{x}
    AND year not like :exclude{x}
    AND bpm not like :exclude{x}
    AND key not like :exclude{x}
    AND time not like :exclude{x}
    AND decade not like :exclude{x}
    AND categories not like :exclude{x}
    AND city not like :exclude{x}
    AND country not like :exclude{x}
    AND description not like :exclude{x}
    AND album not like :exclude{x}
    AND title not like :exclude{x}
    AND artist not like :exclude{x}
)"""
)


def construct_fs_query(args):
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    if args.action == SC.listen:
        for idx, inc in enumerate(args.include):
            cf.append(audio_include_string(idx))
            bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
        for idx, exc in enumerate(args.exclude):
            cf.append(audio_exclude_string(idx))
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
        , size
        {', duration' if args.action in [SC.listen, SC.watch] else ''}
        {', subtitle_count' if args.action == SC.watch else ''}
        {', sparseness' if args.action == SC.filesystem else ''}
        {', is_dir' if args.action == SC.filesystem else ''}
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM media
    WHERE 1=1
    {args.sql_filter}
    {'and audio_count > 0' if args.action == SC.listen else ''}
    {'and video_count > 0' if args.action == SC.watch else ''}
    {f'and path not like "%/{args.keep_dir}%"' if args.post_action == 'askkeep' else ''}
    {'and width < height' if args.portrait else ''}
    {'and is_deleted=0' if args.action in [SC.listen, SC.watch] and 'is_deleted' not in args.sql_filter else ''}
    ORDER BY 1=1
        {',' + args.sort if args.sort else ''}
        {', path' if args.print or args.include or args.play_in_order > 0 else ''}
        {', duration / size ASC' if args.action in [SC.listen, SC.watch] else ''}
    {LIMIT} {OFFSET}
    """

    return query, bindings


def process_actions(args, construct_query=construct_fs_query):
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
    args = parse_args(SC.watch, "video.db", default_chromecast="Living Room TV")
    process_actions(args)


def listen():
    args = parse_args(SC.listen, "audio.db", default_chromecast="Xylo and Orchestra")
    process_actions(args)


def filesystem():
    args = parse_args(SC.filesystem, "fs.db")
    process_actions(args)
