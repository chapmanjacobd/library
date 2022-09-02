import argparse, shlex, shutil
from pathlib import Path
from typing import Dict

import ffmpeg, sqlite_utils
from catt.api import CattDevice
from rich.prompt import Confirm

from xklb import db, paths, utils
from xklb.player import (
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
from xklb.utils import SC, cmd, log


def parse_args(action, default_db, default_chromecast=""):
    parser = argparse.ArgumentParser(
        prog="lb " + action,
        usage=f"""lb {action} [database] [optional args]

    Control playback:

        To stop playback press Ctrl-C in either the terminal or mpv

        Create global shortcuts in your desktop environment by sending commands to mpv_socket:

        echo 'playlist-next force' | socat - /tmp/mpv_socket

    If not specified, {action} will try to read {default_db} in the working directory:

        lb {action}
        lb {action} ./my/other/database/is-a/db.db

    Override the default player (mpv):

        lb does a lot of things to try to automatically use your preferred media player
        but if it doesn't guess right you can make it explicit:

        lb {action} --player "vlc --vlc-opts"

    Cast to chromecast groups:

        lb {action} --cast --cast-to "Office pair"
        lb {action} -ct "Office pair"  # equivalent

        If you don't know the exact name of your chromecast group run `catt scan`

    Print instead of play:

        Generally speaking, you should always be able to add `-p` to check what the play queue will look like before playing--even while using many other option simultaneously.
        The only exceptions that I can think of are `-OO` and `-OOO`. In those cases the results might lie.

        lb {action} --print --limit 10  # print the next 10 files
        lb {action} -p -L 10  # print the next 10 files
        lb {action} -p  # be cautious about running -p on an unfiltered set because this will print _all_ the media

        Printing modes

        lb {action} -p    # print in a table
        lb {action} -p p  # equivalent
        lb {action} -p a  # print an aggregate report
        lb {action} -p f  # print fields -- useful for piping paths to utilities like xargs or GNU Parallel

        Check if you've downloaded something before

        lb {action} -u duration -p -s 'title'

        Print an aggregate report of deleted media

        lb {action} -w is_deleted=1 -p a
        ╒═══════════╤══════════════╤═════════╤═════════╕
        │ path      │ duration     │ size    │   count │
        ╞═══════════╪══════════════╪═════════╪═════════╡
        │ Aggregate │ 14 days, 23  │ 50.6 GB │   29058 │
        │           │ hours and 42 │         │         │
        │           │ minutes      │         │         │
        ╘═══════════╧══════════════╧═════════╧═════════╛
        Total duration: 14 days, 23 hours and 42 minutes


        Print an aggregate report of media that has no duration information (likely corrupt media)

        lb {action} -w 'duration is null' -p a

        Print a list of videos which have below 1280px resolution

        lb wt -w 'width<1280' -p f

        View how much time you have listened to music

        lb lt -w play_count'>'0 -p a

        See how much video you have

        lb wt video.db -p a
        ╒═══════════╤═════════╤═════════╤═════════╕
        │ path      │   hours │ size    │   count │
        ╞═══════════╪═════════╪═════════╪═════════╡
        │ Aggregate │  145769 │ 37.6 TB │  439939 │
        ╘═══════════╧═════════╧═════════╧═════════╛
        Total duration: 16 years, 7 months, 19 days, 17 hours and 25 minutes


        View all the columns

        lb {action} -p -L 1 --cols '*'

        Open ipython with all of your media

        lb {action} -vv -p --cols '*'
        ipdb> len(db_resp)
        462219

    Set the play queue size:

        By default the play queue is 120. Long enough that you probably haven't noticed but short enough that the program is snappy.

        If you want everything in your play queue you can use the aid of infinity.

        Pick your poison (these all do effectively the same thing):
        lb {action} -L inf
        lb {action} -l inf
        lb {action} --queue inf
        lb {action} -L 99999999999999999999999

        You might also want to restrict the play queue when you only want 1000 random files for example:

        lb {action} -u random -L 1000

    Offset the play queue:

        You can also offset the queue. For example if you want to skip one or ten media:

        lb {action} -S 10  # offset ten from the top of an ordered query

    Repeat

        lb {action}                  # listen to 120 random songs (DEFAULT_PLAY_QUEUE)
        lb {action} --limit 5        # listen to FIVE songs
        lb {action} -l inf -u random # listen to random songs indefinitely
        lb {action} -s infinite      # listen to songs from the band infinite

    Constrain media by search:

        Audio files have many tags to readily search through so metadata like artist, album, and even mood are included in search.
        Video files have less consistent metadata and so only paths are included in search.

        lb {action} --include happy  # only matches will be included
        lb {action} -s happy         # equivalent

        lb {action} --exclude sad   # matches will be excluded
        lb {action} -E sad          # equivalent

        Double spaces are parsed as one space

        -s '  ost'        # will match OST and not ghost
        -s toy story      # will match '/folder/toy/something/story.mp3'
        -s 'toy  story'    # will match more strictly '/folder/toy story.mp3'

    Constrain media by arbitrary SQL expressions:

        lb {action} --where audio_count = 2  # media which have two audio tracks
        lb {action} -w "language = 'eng'"    # media which have an English language tag (this could be audio or subtitle)
        lb {action} -w subtitle_count=0      # media that doesn't have subtitles

    Constrain media to duration (in minutes):

        lb {action} --duration 20

        lb {action} -d 6  # 6 mins ±10 percent (ie. between 5 and 7 mins)
        lb {action} -d-6  # less than 6 mins
        lb {action} -d+6  # more than 6 mins

        Can be specified multiple times:

        lb {action} -d+5 -d-7  # should be similar to -d 6

        If you want exact time use `where`

        lb {action} --where 'duration=6*60'

    Constrain media to file size (in megabytes):

        lb {action} --size 20

        lb {action} -z 6  # 6 MB ±10 percent (ie. between 5 and 7 MB)
        lb {action} -z-6  # less than 6 MB
        lb {action} -z+6  # more than 6 MB

    Constrain media by throughput:

        Bitrate information is not explicitly saved but you can use file size and duration as a proxy:

        lb {action} -w 'size/duration<50000'

    Constrain media to portrait orientation video:

        lb {action} --portrait
        lb {action} -w 'width<height' # equivalent

    Specify media play order:

        lb {action} --sort duration   # play shortest media first
        lb {action} -u duration desc  # play longest media first

        You can use multiple SQL ORDER BY expressions

        lb {action} -u subtitle_count > 0 desc # play media that has at least one subtitle first

    Play media in order (similarly named episodes):

        lb {action} --play-in-order

        There are multiple strictness levels of --play-in-order.
        If things aren't playing in order try adding more `O`s:

        lb {action} -O    # normal
        lb {action} -OO   # slower, more complex algorithm
        lb {action} -OOO  # strict

    Post-actions -- choose what to do after playing:

        lb {action} --post-action delete  # delete file after playing
        lb {action} -k ask  # ask after each whether to keep or delete
        lb {action} -k askkeep  # ask after each whether to move to a keep folder or delete

        The default location of the keep folder is ./keep/ relative to each individual media file
        You can change this by explicitly setting an absolute `keep-dir` path:

        lb {action} -k askkeep --keep-dir /home/my/music/keep/

    Experimental options:

        Duration to play (in seconds) while changing the channel

        lb {action} --interdimensional-cable 40
        lb {action} -4dtv 40
""",
    )

    parser.add_argument(
        "database",
        nargs="?",
        default=default_db,
        help="Database file. If not specified a generic name will be used: audio.db, video.db, fs.db, etc",
    )

    # TODO: maybe try https://dba.stackexchange.com/questions/43415/algorithm-for-finding-the-longest-prefix
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
    parser.add_argument("--portrait", "-portrait", action="store_true", help=argparse.SUPPRESS)

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
    parser.add_argument("--player", "-player", help=argparse.SUPPRESS)
    parser.add_argument("--mpv-socket", default=paths.DEFAULT_MPV_SOCKET, help=argparse.SUPPRESS)

    parser.add_argument(
        "--player-args-when-sub", "-player-sub", nargs="*", default=["--speed=1"], help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--player-args-when-no-sub", "-player-no-sub", nargs="*", default=["--speed=1.46"], help=argparse.SUPPRESS
    )
    parser.add_argument("--transcode", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--post-action", "--action", "-k", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--keep-dir", "--keepdir", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--shallow-organize", default="/mnt/d/", help=argparse.SUPPRESS)

    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--ignore-errors", "--ignoreerrors", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db

    if not args.limit and all([not args.print, args.action in [SC.listen, SC.watch, SC.tubelisten, SC.tubewatch]]):
        args.limit = utils.DEFAULT_PLAY_QUEUE
    elif args.limit in ["inf", "all"]:
        args.limit = None

    if not args.sort:
        if args.action in [SC.listen, SC.watch]:
            args.sort = ["priority"]
            if args.include:
                args.sort = ["duration desc"]
                if args.print:
                    args.sort = ["duration"]

        elif args.action in [SC.tubelisten, SC.tubewatch]:
            args.sort = ["play_count, random"]
            if args.include:
                args.sort = ["playlist_path, duration desc"]
                if args.print:
                    args.sort = ["playlist_path, duration"]

        elif args.action in [SC.filesystem]:
            args.sort = ["sparseness, size"]

    if args.random:
        args.sort = ["random"]

    if args.sort:
        args.sort = " ".join(args.sort)
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


def play(args, m: Dict):
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
            return
        media_file = str(media_path)

        if args.transcode:
            media_file = transcode(media_file)

    if args.action == SC.listen:
        print(cmd("ffprobe", "-hide_banner", "-loglevel", "info", media_file).stderr)
    else:
        print(media_file)

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


def construct_search_bindings(args, bindings, cf, include_func, exclude_func):
    for idx, inc in enumerate(args.include):
        cf.append(include_func(idx))
        bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        cf.append(exclude_func(idx))
        bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"


def substring_search(args, cf, bindings):
    if args.action == SC.listen:
        construct_search_bindings(args, bindings, cf, audio_include_string, audio_exclude_string)
    elif args.action == SC.watch:
        construct_search_bindings(args, bindings, cf, video_include_string, video_exclude_string)
    else:
        construct_search_bindings(args, bindings, cf, other_include_string, other_exclude_string)


def construct_fs_query(args):
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)

    cf.extend([" and " + w for w in args.where])

    table = "media"
    if args.include:
        table = db.fts_search(args, bindings)
    elif args.exclude:
        substring_search(args, cf, bindings)

    args.sql_filter = " ".join(cf)
    args.sql_filter_bindings = bindings

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip else ""

    query = f"""SELECT path
        , size
        {', duration' if args.action in [SC.listen, SC.watch] else ''}
        {', subtitle_count' if args.action == SC.watch else ''}
        {', sparseness' if args.action == SC.filesystem else ''}
        {', is_dir' if args.action == SC.filesystem else ''}
        {', ' + ', '.join(args.cols) if args.cols else ''}
    FROM {table}
    WHERE 1=1
    {'and rowid in (select rowid from media order by random() limit 60000)' if table == 'media' and not args.print else ''}
    {args.sql_filter}
    {'and audio_count > 0' if args.action == SC.listen else ''}
    {'and video_count > 0' if args.action == SC.watch else ''}
    {f'and path not like "%{args.keep_dir}%"' if args.post_action == 'askkeep' else ''}
    {'and width < height' if args.portrait else ''}
    {'and is_deleted=0' if args.action in [SC.listen, SC.watch] and 'is_deleted' not in args.sql_filter else ''}
    ORDER BY 1=1
        {',' + args.sort if args.sort else ''}
        {', path' if args.print or args.include or args.play_in_order > 0 else ''}
        , random()
    {LIMIT} {OFFSET}
    """

    return query, bindings


def process_playqueue(args, construct_query=construct_fs_query):
    args.db = db.connect(args)
    query, bindings = construct_query(args)

    if args.print:
        return printer(args, query, bindings)

    media = list(args.db.query(query, bindings))

    if len(media) == 0:
        print("No media found")
        exit(2)

    try:
        for m in media:
            play(args, m)
    finally:
        if args.interdimensional_cable:
            args.sock.send((f"raw quit \n").encode("utf-8"))
        Path(args.mpv_socket).unlink(missing_ok=True)
        if args.chromecast:
            Path(paths.CAST_NOW_PLAYING).unlink(missing_ok=True)


def watch():
    args = parse_args(SC.watch, "video.db", default_chromecast="Living Room TV")
    process_playqueue(args)


def listen():
    args = parse_args(SC.listen, "audio.db", default_chromecast="Xylo and Orchestra")
    process_playqueue(args)


def filesystem():
    args = parse_args(SC.filesystem, "fs.db")
    process_playqueue(args)
