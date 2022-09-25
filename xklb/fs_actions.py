import argparse, operator, shlex, shutil
from pathlib import Path
from random import random
from typing import Dict, Tuple

from catt.api import CattDevice

from xklb import db, paths, player, utils
from xklb.player import get_ordinal_media, mark_media_deleted, override_sort
from xklb.subtitle import externalize_subtitle
from xklb.utils import DEFAULT_MULTIPLE_PLAYBACK, DEFAULT_PLAY_QUEUE, SC, cmd, log

DEFAULT_PLAYER_ARGS_SUB = ["--speed=1"]
DEFAULT_PLAYER_ARGS_NO_SUB = ["--speed=1.46"]


def fs_actions_usage(action, default_db) -> str:
    return f"""library {action} [database] [optional args]

    Control playback:
        To stop playback press Ctrl-C in either the terminal or mpv

        Create global shortcuts in your desktop environment by sending commands to mpv_socket:
        echo 'playlist-next force' | socat - /tmp/mpv_socket

    If not specified, {action} will try to read {default_db} in the working directory:
        library {action}
        library {action} ./my/other/database/is-a/db.db

    Override the default player (mpv):
        library does a lot of things to try to automatically use your preferred media player
        but if it doesn't guess right you can make it explicit:
        library {action} --player "vlc --vlc-opts"

    Cast to chromecast groups:
        library {action} --cast --cast-to "Office pair"
        library {action} -ct "Office pair"  # equivalent
        If you don't know the exact name of your chromecast group run `catt scan`

    Print instead of play:
        library {action} --print --limit 10  # print the next 10 files
        library {action} -p -L 10  # print the next 10 files
        library {action} -p  # this will print _all_ the media. be cautious about `-p` on an unfiltered set

        Printing modes
        library {action} -p    # print in a table
        library {action} -p p  # equivalent
        library {action} -p a  # print an aggregate report
        library {action} -p f  # print fields -- useful for piping paths to utilities like xargs or GNU Parallel

        Check if you have downloaded something before
        library {action} -u duration -p -s 'title'

        Print an aggregate report of deleted media
        library {action} -w is_deleted=1 -p=a
        ╒═══════════╤══════════════╤═════════╤═════════╕
        │ path      │ duration     │ size    │   count │
        ╞═══════════╪══════════════╪═════════╪═════════╡
        │ Aggregate │ 14 days, 23  │ 50.6 GB │   29058 │
        │           │ hours and 42 │         │         │
        │           │ minutes      │         │         │
        ╘═══════════╧══════════════╧═════════╧═════════╛
        Total duration: 14 days, 23 hours and 42 minutes

        Print an aggregate report of media that has no duration information (likely corrupt media)
        library {action} -w 'duration is null' -p=a

        Print a list of filenames which have below 1280px resolution
        library wt -w 'width<1280' -p=f

        Print media you have partially viewed with mpv
        library {action} -p=v

        View how much time you have {action}ed
        library {action} -w play_count'>'0 -p=a

        See how much video you have
        library wt video.db -p=a
        ╒═══════════╤═════════╤═════════╤═════════╕
        │ path      │   hours │ size    │   count │
        ╞═══════════╪═════════╪═════════╪═════════╡
        │ Aggregate │  145769 │ 37.6 TB │  439939 │
        ╘═══════════╧═════════╧═════════╧═════════╛
        Total duration: 16 years, 7 months, 19 days, 17 hours and 25 minutes

        View all the columns
        library {action} -p -L 1 --cols '*'

        Open ipython with all of your media
        library {action} -vv -p --cols '*'
        ipdb> len(db_resp)
        462219

    Set the play queue size:
        By default the play queue is 120--long enough that you likely have not noticed
        but short enough that the program is snappy.

        If you want everything in your play queue you can use the aid of infinity.
        Pick your poison (these all do effectively the same thing):
        library {action} -L inf
        library {action} -l inf
        library {action} --queue inf
        library {action} -L 99999999999999999999999

        You may also want to restrict the play queue.
        For example, when you only want 1000 random files:
        library {action} -u random -L 1000

    Offset the play queue:
        You can also offset the queue. For example if you want to skip one or ten media:
        library {action} -S 10  # offset ten from the top of an ordered query

    Repeat
        library {action}                  # listen to 120 random songs (DEFAULT_PLAY_QUEUE)
        library {action} --limit 5        # listen to FIVE songs
        library {action} -l inf -u random # listen to random songs indefinitely
        library {action} -s infinite      # listen to songs from the band infinite

    Constrain media by search:
        Audio files have many tags to readily search through so metadata like artist,
        album, and even mood are included in search.
        Video files have less consistent metadata and so only paths are included in search.
        library {action} --include happy  # only matches will be included
        library {action} -s happy         # equivalent
        library {action} --exclude sad    # matches will be excluded
        library {action} -E sad           # equivalent

        Search only the path column
        library {action} -O -s 'path : mad max'
        library {action} -O -s 'path : "mad max"' # add "quotes" to be more strict

        Double spaces are parsed as one space
        -s '  ost'        # will match OST and not ghost
        -s toy story      # will match '/folder/toy/something/story.mp3'
        -s 'toy  story'   # will match more strictly '/folder/toy story.mp3'

    Constrain media by arbitrary SQL expressions:
        library {action} --where audio_count = 2  # media which have two audio tracks
        library {action} -w "language = 'eng'"    # media which have an English language tag
                                                    (this could be audio _or_ subtitle)
        library {action} -w subtitle_count=0      # media that doesn't have subtitles

    Constrain media to duration (in minutes):
        library {action} --duration 20
        library {action} -d 6  # 6 mins ±10 percent (ie. between 5 and 7 mins)
        library {action} -d-6  # less than 6 mins
        library {action} -d+6  # more than 6 mins

        Duration can be specified multiple times:
        library {action} -d+5 -d-7  # should be similar to -d 6

        If you want exact time use `where`
        library {action} --where 'duration=6*60'

    Constrain media to file size (in megabytes):
        library {action} --size 20
        library {action} -z 6  # 6 MB ±10 percent (ie. between 5 and 7 MB)
        library {action} -z-6  # less than 6 MB
        library {action} -z+6  # more than 6 MB

    Constrain media by throughput:
        Bitrate information is not explicitly saved.
        You can use file size and duration as a proxy for throughput:
        library {action} -w 'size/duration<50000'

    Constrain media to portrait orientation video:
        library {action} --portrait
        library {action} -w 'width<height' # equivalent

    Specify media play order:
        library {action} --sort duration   # play shortest media first
        library {action} -u duration desc  # play longest media first
        You can use multiple SQL ORDER BY expressions
        library {action} -u subtitle_count > 0 desc # play media that has at least one subtitle first

    Play media in order (similarly named episodes):
        library {action} --play-in-order
        There are multiple strictness levels of --play-in-order.
        If things aren't playing in order try adding more `O`s:
        library {action} -O    # fast
        library {action} -OO   # slow, more complex algorithm
        library {action} -OOO  # slow, ignores most filters

    Post-actions -- choose what to do after playing:
        library {action} --post-action delete  # delete file after playing
        library {action} -k ask  # ask after each whether to keep or delete

        library {action} -k askkeep  # ask after each whether to move to a keep folder or delete
        The default location of the keep folder is ./keep/ (relative to the played media file)
        You can change this by explicitly setting an *absolute* `keep-dir` path:
        library {action} -k askkeep --keep-dir /home/my/music/keep/

    Experimental options:
        Duration to play (in seconds) while changing the channel
        library {action} --interdimensional-cable 40
        library {action} -4dtv 40

        Playback multiple files at once
        library {action} --multiple-playback    # one per display; or two if only one display detected
        library {action} --multiple-playback 4  # play four media at once, divide by available screens
        library {action} -m 4 --screen-name eDP # play four media at once on specific screen
        library {action} -m 4 --loop --crop     # play four cropped videos on a loop
        library {action} -m 4 --hstack          # use hstack style
"""


def parse_args(action, default_db, default_chromecast="") -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library " + action, usage=fs_actions_usage(action, default_db))

    parser.add_argument(
        "database",
        nargs="?",
        default=default_db,
        help=f"Database file. If not specified a generic name will be used: {default_db}",
    )

    parser.add_argument("--play-in-order", "-O", action="count", default=0, help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--random", "-r", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)

    parser.add_argument("--chromecast-device", "--cast-to", "-t", default=default_chromecast, help=argparse.SUPPRESS)
    parser.add_argument("--chromecast", "--cast", "-c", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--with-local", "-wl", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--interdimensional-cable", "-4dtv", type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        "--multiple-playback",
        "-m",
        default=False,
        nargs="?",
        const=DEFAULT_MULTIPLE_PLAYBACK,
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--screen-name", help=argparse.SUPPRESS)
    parser.add_argument("--loop", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--crop", "--zoom", "--stretch", "--fit", "--fill", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--portrait", "-portrait", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--hstack", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--vstack", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--prefix", default="", help=argparse.SUPPRESS)

    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--size", "-z", action="append", help=argparse.SUPPRESS)

    parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--moved", nargs=2, help=argparse.SUPPRESS)

    parser.add_argument("--cols", "-cols", "-col", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--skip", "-S", help=argparse.SUPPRESS)

    parser.add_argument("--start", "-vs", help=argparse.SUPPRESS)
    parser.add_argument("--end", "-ve", help=argparse.SUPPRESS)
    parser.add_argument("--mpv-socket", default=paths.DEFAULT_MPV_SOCKET, help=argparse.SUPPRESS)
    parser.add_argument("--watch-later-directory", default=paths.DEFAULT_MPV_WATCH_LATER, help=argparse.SUPPRESS)

    parser.add_argument("--player", "-player", help=argparse.SUPPRESS)
    parser.add_argument(
        "--player-args-sub", "-player-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_SUB, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--player-args-no-sub", "-player-no-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_NO_SUB, help=argparse.SUPPRESS
    )
    parser.add_argument("--transcode", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--post-action", "--action", "-k", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--keep-dir", "--keepdir", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--shallow-organize", default="/mnt/d/", help=argparse.SUPPRESS)

    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.action = action
    args.defaults = []

    if args.db:
        args.database = args.db

    if not args.limit:
        args.defaults.append("limit")
        if all([not args.print, args.action in [SC.listen, SC.watch, SC.tubelisten, SC.tubewatch, SC.read]]):
            args.limit = utils.DEFAULT_PLAY_QUEUE
        elif all([not args.print, args.action in [SC.view]]):
            args.limit = utils.DEFAULT_PLAY_QUEUE * 4
    elif args.limit in ["inf", "all"]:
        args.limit = None

    if not args.sort:
        args.defaults.append("sort")

        if args.action in [SC.listen, SC.watch]:
            args.sort = ["priority"]
            if args.include:
                args.sort = ["duration desc", "size desc"]
                if args.print:
                    args.sort = ["duration", "size"]

        elif args.action in [SC.tubelisten, SC.tubewatch]:
            args.sort = ["play_count", "random"]
            if args.include:
                args.sort = ["playlist_path", "duration desc"]
                if args.print:
                    args.sort = ["playlist_path", "duration"]

        elif args.action in [SC.filesystem]:
            args.sort = ["sparseness", "size"]

    if args.sort:
        if args.play_in_order > 0:
            args.sort.append("path")

        args.sort = ",".join(args.sort).replace(",,", ",")
        args.sort = override_sort(args.sort)

    if args.cols:
        args.cols = list(utils.flatten([s.split(",") for s in args.cols]))

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
        args.cc_ip = utils.get_ip_of_chromecast(args.chromecast_device)

    if args.player:
        args.player = shlex.split(args.player)

    log.info(utils.dict_filter_bool(args.__dict__))

    args.sock = None
    return args


def transcode(next_video):
    temp_video = cmd("mktemp", "--suffix=.mkv", "--dry-run").stdout.strip()
    shutil.move(next_video, temp_video)
    next_video = str(Path(next_video).with_suffix(".mkv"))
    cmd(
        (
            f"ffmpeg -nostdin -loglevel error -stats -i {temp_video} -map 0 -scodec webvtt -vcodec h264"
            " -preset fast -profile:v high -level 4.1 -crf 17 -pix_fmt yuv420p"
            " -acodec opus -ac 2 -b:a 128k -filter:a loudnorm=i=-18:lra=17"
            f" {next_video} && rm {temp_video}"
        )
    )
    print(next_video)
    return next_video


def chromecast_play(args, m) -> None:
    if args.action in [SC.watch, SC.tubewatch]:
        catt_log = player.watch_chromecast(args, m, subtitles_file=externalize_subtitle(m["path"]))
    elif args.action in [SC.listen, SC.tubelisten]:
        catt_log = player.listen_chromecast(args, m)
    else:
        raise NotImplementedError

    if catt_log:
        if catt_log.stderr is None or catt_log.stderr == "":
            if not args.with_local:
                raise Exception("catt does not exit nonzero? but something might have gone wrong")
        elif "Heartbeat timeout, resetting connection" in catt_log.stderr:
            raise Exception("Media is possibly partially unwatched")


def is_play_in_order_lvl2(args, media_file) -> bool:
    return any(
        [
            args.play_in_order >= 2 and args.action not in [SC.listen, SC.tubelisten],
            args.play_in_order >= 1 and args.action == SC.listen and "audiobook" in media_file.lower(),
        ]
    )


def play(args, m: Dict) -> None:
    media_file = m["path"]

    if is_play_in_order_lvl2(args, media_file):
        media_file = get_ordinal_media(args, media_file)

    if args.action in [SC.watch, SC.listen]:
        media_path = Path(args.prefix + media_file).resolve()
        if not media_path.exists():
            if args.is_mounted:
                mark_media_deleted(args, media_file)
            log.info("[%s]: Does not exist. Skipping...", media_file)
            return
        media_file = str(media_path)

        if args.transcode:
            media_file = transcode(media_file)

    if args.action == SC.listen:
        print(cmd("ffprobe", "-hide_banner", "-loglevel", "info", media_file).stderr)
    else:
        print(media_file)

    args.player = player.parse(args, m, media_file)

    if args.chromecast:
        try:
            chromecast_play(args, m)
        except Exception as e:
            if args.ignore_errors:
                return
            else:
                raise e
        else:
            player.post_act(args, media_file)

    elif args.interdimensional_cable:
        player.socket_play(args, m)

    else:
        r = player.local_player(args, m, media_file)
        if r.returncode != 0:
            print("Player exited with code", r.returncode)
            if args.ignore_errors:
                return
            else:
                exit(r.returncode)

        if args.action in [SC.listen, SC.watch, SC.tubelisten, SC.tubewatch]:
            player.post_act(args, media_file)


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

video_include_string = (
    lambda x: f"""and (
    path like :include{x}
    OR tags like :include{x}
)"""
)

video_exclude_string = (
    lambda x: f"""and (
    path not like :exclude{x}
    AND tags not like :exclude{x}
)"""
)

other_include_string = lambda x: f"and path like :include{x}"
other_exclude_string = lambda x: f"and path not like :exclude{x}"


def construct_search_bindings(args, bindings, cf, include_func, exclude_func) -> None:
    for idx, inc in enumerate(args.include):
        cf.append(include_func(idx))
        bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        cf.append(exclude_func(idx))
        bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"


def search_substring(args, cf, bindings) -> None:
    if args.action == SC.watch:
        construct_search_bindings(args, bindings, cf, video_include_string, video_exclude_string)
    elif args.action == SC.listen:
        construct_search_bindings(args, bindings, cf, audio_include_string, audio_exclude_string)
    else:  # args.action == SC.filesystem
        construct_search_bindings(args, bindings, cf, other_include_string, other_exclude_string)


def construct_fs_query(args) -> Tuple[str, dict]:
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    args.table = "media"
    if args.db["media"].detect_fts():
        if args.include:
            args.table = db.fts_search(args, bindings)
        elif args.exclude:
            search_substring(args, cf, bindings)
    else:
        search_substring(args, cf, bindings)

    if args.table == "media" and not args.print:
        limit = 60_000
        if args.random:
            if args.include:
                args.sort = "random(), " + args.sort
            else:
                limit = DEFAULT_PLAY_QUEUE * 16
        cf.append(f"and rowid in (select rowid from media order by random() limit {limit})")

    args.sql_filter = " ".join(cf)
    args.sql_filter_bindings = bindings

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    # switching between videos with and without subs is annoying
    subtitle_count = ">0"
    if random() < 0.659:  # bias slightly toward videos without subtitles
        subtitle_count = "=0"

    query = f"""SELECT path
        , size
        {', duration' if args.action in [SC.listen, SC.watch] else ''}
        {', cast(length(tags) / 4.2 / 220 * 60 as INT) + 10 duration' if args.action == SC.read else ''}
        {', subtitle_count' if args.action == SC.watch else ''}
        {', sparseness' if args.action == SC.filesystem else ''}
        {', is_dir' if args.action == SC.filesystem else ''}
        {', ' + ', '.join(args.cols) if args.cols and args.cols != ['duration'] else ''}
    FROM {args.table}
    WHERE 1=1
        {args.sql_filter}
        {f'and path not like "%{args.keep_dir}%"' if args.post_action == 'askkeep' else ''}
        {'and is_deleted=0' if args.action in [SC.listen, SC.watch] and 'is_deleted' not in args.sql_filter else ''}
    ORDER BY 1=1
        {', video_count > 0 desc' if args.action == SC.watch else ''}
        {', audio_count > 0 desc' if args.action == SC.listen else ''}
        {', width < height desc' if args.portrait else ''}
        {f', subtitle_count {subtitle_count} desc' if args.action == SC.watch and not args.print else ''}
        {',' + args.sort if args.sort else ''}
        , random()
    {LIMIT} {OFFSET}
    """

    return query, bindings


def process_playqueue(args, construct_query=construct_fs_query) -> None:
    args.db = db.connect(args)
    query, bindings = construct_query(args)

    if args.print:
        player.printer(args, query, bindings)
        return None

    media = list(args.db.query(query, bindings))

    if len(media) == 0:
        print("No media found")
        exit(2)

    if all([Path(args.watch_later_directory).exists(), args.play_in_order != 2, "sort" in args.defaults]):
        media = utils.mpv_enrich(args, media)

    args.is_mounted = paths.is_mounted(list(map(operator.itemgetter("path"), media)), args.shallow_organize)

    if args.multiple_playback:
        player.multiple_player(args, media)
    else:
        try:
            for m in media:
                play(args, m)
        finally:
            if args.interdimensional_cable:
                args.sock.send((f"raw quit \n").encode("utf-8"))
            Path(args.mpv_socket).unlink(missing_ok=True)
            if args.chromecast:
                Path(paths.CAST_NOW_PLAYING).unlink(missing_ok=True)


def watch() -> None:
    args = parse_args(SC.watch, "video.db", default_chromecast="Living Room TV")
    process_playqueue(args)


def listen() -> None:
    args = parse_args(SC.listen, "audio.db", default_chromecast="Xylo and Orchestra")
    process_playqueue(args)


def filesystem() -> None:
    args = parse_args(SC.filesystem, "fs.db")
    process_playqueue(args)


def read() -> None:
    args = parse_args(SC.read, "text.db")
    process_playqueue(args)


def view() -> None:
    args = parse_args(SC.view, "image.db")
    process_playqueue(args)
