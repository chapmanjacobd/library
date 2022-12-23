import argparse, shlex, shutil
from pathlib import Path
from random import random
from typing import Dict, Tuple

from xklb import consts, db, player, tube_backend, utils
from xklb.consts import SC
from xklb.player import get_ordinal_media, mark_media_deleted, override_sort
from xklb.subtitle import externalize_subtitle
from xklb.utils import cmd, log


def construct_search_bindings(args, cf, bindings, columns) -> None:
    includes, excludes = db.gen_include_excludes(columns)

    for idx, inc in enumerate(args.include):
        cf.append(includes.format(idx))
        bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        cf.append(excludes.format(idx))
        bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"


def construct_query(args) -> Tuple[str, dict]:
    m_columns = args.db["media"].columns_dict
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        cf.append(" and size IS NOT NULL " + args.size)
    if args.duration_from_size:
        cf.append(
            " and size IS NOT NULL and duration in (select distinct duration from m where 1=1 "
            + args.duration_from_size
            + ")"
        )

    cf.extend([" and " + w for w in args.where])

    def ii(string):
        if string.isdigit():
            return string + " minutes"
        return string.replace("mins", "minutes").replace("secs", "seconds")

    if args.created_within:
        cf.append(f"and time_created > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.created_within)}')) as int)")
    if args.created_before:
        cf.append(f"and time_created < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.created_before)}')) as int)")
    if args.changed_within:
        cf.append(f"and time_modified > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.changed_within)}')) as int)")
    if args.changed_before:
        cf.append(f"and time_modified < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.changed_before)}')) as int)")
    if args.played_within:
        cf.append(f"and time_played > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.played_within)}')) as int)")
    if args.played_before:
        cf.append(f"and time_played < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.played_before)}')) as int)")
    if args.deleted_within:
        cf.append(f"and time_deleted > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.deleted_within)}')) as int)")
    if args.deleted_before:
        cf.append(f"and time_deleted < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.deleted_before)}')) as int)")

    args.table = "media"
    if args.db["media"].detect_fts():
        if args.include:
            args.table = db.fts_search(args, bindings)
            m_columns = {**m_columns, "rank": int}
        elif args.exclude:
            construct_search_bindings(args, cf, bindings, m_columns)
    else:
        construct_search_bindings(args, cf, bindings, m_columns)

    if args.table == "media" and not any(
        [cf, args.where, args.print, args.partial, args.limit != consts.DEFAULT_PLAY_QUEUE, args.duration_from_size]
    ):
        limit = 60_000
        if args.random:
            limit = consts.DEFAULT_PLAY_QUEUE * 16

        if "limit" in args.defaults:
            cf.append(f"and m.rowid in (select rowid from media order by random() limit {limit})")
    else:
        if args.random:
            args.sort = "random(), " + args.sort

    args.sql_filter = " ".join(cf)
    args.sql_filter_bindings = bindings

    # switching between videos with and without subs is annoying
    subtitle_count = ">0"
    if random() < 0.659:  # bias slightly toward videos without subtitles
        subtitle_count = "=0"

    duration = "duration"
    if args.action == SC.read:
        duration = "cast(length(tags) / 4.2 / 220 * 60 as INT) + 10 duration"

    cols = args.cols or ["path", "title", duration, "size", "subtitle_count", "is_dir", "rank"]
    SELECT = "\n,".join([c for c in cols if c in m_columns or c == "*"])
    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip and args.limit else ""
    query = f"""WITH m as (
    SELECT rowid, * FROM {args.table}
    WHERE 1=1
        {f'and path like "http%"' if args.safe else ''}
        {f'and path not like "{Path(args.keep_dir).resolve()}%"' if args.post_action == 'askkeep' else ''}
        {'and time_deleted=0' if 'time_deleted' in m_columns and 'time_deleted' not in args.sql_filter else ''}
        {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
        {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
        {'AND time_downloaded = 0' if args.online_media_only else ''}
        {'AND time_downloaded > 0 AND path not like "http%"' if args.local_media_only else ''}
    )
    SELECT
        {SELECT}
    FROM m
    WHERE 1=1
        {args.sql_filter}
    ORDER BY 1=1
        {', video_count > 0 desc' if 'video_count' in m_columns and args.action == SC.watch else ''}
        {', audio_count > 0 desc' if 'audio_count' in m_columns else ''}
        {', time_downloaded > 0 desc' if 'time_downloaded' in m_columns and 'time_downloaded' not in args.sql_filter else ''}
        , path like "http%"
        {', width < height desc' if 'width' in m_columns and args.portrait else ''}
        {f', subtitle_count {subtitle_count} desc' if 'subtitle_count' in m_columns and args.action == SC.watch and not any([args.print, consts.PYTEST_RUNNING, 'subtitle_count' in args.where, args.limit != consts.DEFAULT_PLAY_QUEUE]) else ''}
        {', ' + args.sort if args.sort else ''}
        , path
        , random()
    {LIMIT} {OFFSET}
    """

    return query, bindings


def usage(action, default_db) -> str:
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

    Play media in order (similarly named episodes):
        library {action} --play-in-order
        There are multiple strictness levels of --play-in-order:
        library {action} -O   # slow, more complex algorithm
        library {action} -OO  # above, plus ignores most filters
        library {action} -OOO # above, plus ignores include/exclude filter during ordinal search

    Play recent partially-watched videos (requires mpv history):
        library {action} --partial       # play newest first
        library {action} --partial old   # play oldest first
        library {action} -P o            # equivalent
        library {action} -P fo           # use file creation time instead of modified time

        library {action} -P p            # sort by progress / duration
        library {action} -P s            # skip partially watched (only show unseen)

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
        library {action} -w time_deleted!=0 -p=a
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
        library {action} -w 'width<1280' -p=f

        Print media you have partially viewed with mpv
        library {action} -p=v

        View how much time you have {action}ed
        library {action} -w play_count'>'0 -p=a

        See how much video you have
        library {action} video.db -p=a
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
        ipdb> len(media)
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

    Constrain media by time_created / time_played / time_deleted / time_modified:
        library {action} --created-within '3 days'
        library {action} --created-before '3 years'

    Constrain media by throughput:
        Bitrate information is not explicitly saved.
        You can use file size and duration as a proxy for throughput:
        library {action} -w 'size/duration<50000'

    Constrain media to portrait orientation video:
        library {action} --portrait
        library {action} -w 'width<height' # equivalent

    Constrain media to duration of videos which match any size constraints:
        library {action} --duration-from-size +700 -u 'duration desc, size desc'

    Constrain media to online-media or local-media:
        Not to be confused with only local-media which is not "offline" (ie. one HDD disconnected)
        library {action} --online-media-only
        library {action} --online-media-only -i  # and ignore playback errors (ie. YouTube video deleted)
        library {action} --local-media-only

    Specify media play order:
        library {action} --sort duration   # play shortest media first
        library {action} -u duration desc  # play longest media first
        You can use multiple SQL ORDER BY expressions
        library {action} -u 'subtitle_count > 0 desc' # play media that has at least one subtitle first

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


def parse_size(size):
    B_TO_MB = 1024 * 1024
    size_mb = 0
    size_rules = ""

    for size_rule in size:
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
    return size_rules


def parse_duration(args):
    SEC_FROM_M = 60
    duration_m = 0
    duration_rules = ""

    for duration_rule in args.duration:
        if "+" in duration_rule:
            # min duration rule
            duration_rules += f"and duration >= {int(abs(float(duration_rule)) * SEC_FROM_M)} "
        elif "-" in duration_rule:
            # max duration rule
            duration_rules += f"and {int(abs(float(duration_rule)) * SEC_FROM_M)} >= duration "
        else:
            # approximate duration rule
            duration_m = float(duration_rule) * SEC_FROM_M
            duration_rules += f"and {int(duration_m + (duration_m /10))} >= duration and duration >= {int(duration_m - (duration_m /10))} "

    return duration_rules


def parse_args(action, default_db, default_chromecast="") -> argparse.Namespace:
    DEFAULT_PLAYER_ARGS_SUB = ["--speed=1"]
    DEFAULT_PLAYER_ARGS_NO_SUB = ["--speed=1.46"]

    parser = argparse.ArgumentParser(prog="library " + action, usage=usage(action, default_db))

    parser.add_argument("--play-in-order", "-O", action="count", default=0, help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--random", "-r", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)

    parser.add_argument("--created-within", help=argparse.SUPPRESS)
    parser.add_argument("--created-before", help=argparse.SUPPRESS)
    parser.add_argument("--changed-within", "--modified-within", help=argparse.SUPPRESS)
    parser.add_argument("--changed-before", "--modified-before", help=argparse.SUPPRESS)
    parser.add_argument("--played-within", help=argparse.SUPPRESS)
    parser.add_argument("--played-before", help=argparse.SUPPRESS)
    parser.add_argument("--deleted-within", help=argparse.SUPPRESS)
    parser.add_argument("--deleted-before", help=argparse.SUPPRESS)

    parser.add_argument("--chromecast-device", "--cast-to", "-t", default=default_chromecast, help=argparse.SUPPRESS)
    parser.add_argument("--chromecast", "--cast", "-c", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--with-local", "-wl", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--loop", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--interdimensional-cable", "-4dtv", type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        "--multiple-playback",
        "-m",
        default=False,
        nargs="?",
        const=consts.DEFAULT_MULTIPLE_PLAYBACK,
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--screen-name", help=argparse.SUPPRESS)
    parser.add_argument("--crop", "--zoom", "--stretch", "--fit", "--fill", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--hstack", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--vstack", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--portrait", "-portrait", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--prefix", default="", help=argparse.SUPPRESS)

    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--size", "-z", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--duration-from-size", action="append", help=argparse.SUPPRESS)

    parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--moved", nargs=2, help=argparse.SUPPRESS)

    parser.add_argument("--cols", "-cols", "-col", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--skip", "-S", help=argparse.SUPPRESS)
    parser.add_argument(
        "--partial", "-P", "--recent", "-R", default=False, const="n", nargs="?", help=argparse.SUPPRESS
    )

    parser.add_argument("--start", "-vs", help=argparse.SUPPRESS)
    parser.add_argument("--end", "-ve", help=argparse.SUPPRESS)
    parser.add_argument("--mpv-socket", default=consts.DEFAULT_MPV_SOCKET, help=argparse.SUPPRESS)
    parser.add_argument("--watch-later-directory", default=consts.DEFAULT_MPV_WATCH_LATER, help=argparse.SUPPRESS)

    parser.add_argument("--override-player", "--player", "-player", help=argparse.SUPPRESS)
    parser.add_argument(
        "--player-args-sub", "-player-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_SUB, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--player-args-no-sub", "-player-no-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_NO_SUB, help=argparse.SUPPRESS
    )
    parser.add_argument("--transcode", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--post-action", "--action", "-k", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--keep-dir", "--keepdir", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--keep-cmd", "--keepcmd", help=argparse.SUPPRESS)
    parser.add_argument("--shallow-organize", default="/mnt/d/", help=argparse.SUPPRESS)

    parser.add_argument("--online-media-only", "--online-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local-media-only", "--local-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")

    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument(
        "database",
        nargs="?",
        default=default_db,
        help=f"Database file. If not specified a generic name will be used: {default_db}",
    )
    args = parser.parse_args()
    args.action = action
    args.defaults = []

    if args.db:
        args.database = args.db
    args.db = db.connect(args)

    if not args.limit:
        args.defaults.append("limit")
        if all([not args.print, not args.partial, args.action in (SC.listen, SC.watch, SC.read)]):
            args.limit = consts.DEFAULT_PLAY_QUEUE
        elif all([not args.print, not args.partial, args.action in (SC.view)]):
            args.limit = consts.DEFAULT_PLAY_QUEUE * 4
    elif args.limit in ("inf", "all"):
        args.limit = None

    if args.sort:
        args.sort = " ".join(args.sort).split(",")
    elif not args.sort:
        args.defaults.append("sort")
        columns = args.db["media"].columns_dict

        args.sort = []
        if args.action in (SC.filesystem):
            args.sort.extend(["sparseness", "size"])
        elif args.action in (SC.listen, SC.watch):
            if "play_count" in columns:
                args.sort.extend(["play_count"])
            if "size" in columns and "duration" in columns:
                args.sort.extend(["priority"])
                if args.include:
                    args.sort = ["duration desc", "size desc"]
                    if args.print:
                        args.sort = ["duration", "size"]

    args.sort = [override_sort(s) for s in args.sort]
    args.sort = ",".join(args.sort).replace(",,", ",")

    if args.cols:
        args.cols = list(utils.flatten([s.split(",") for s in args.cols]))

    if args.duration:
        args.duration = parse_duration(args)

    if args.size:
        args.size = parse_size(args.size)

    if args.duration_from_size:
        args.duration_from_size = parse_size(args.duration_from_size)

    if args.chromecast:
        from catt.api import CattDevice

        args.cc = CattDevice(args.chromecast_device, lazy=True)
        args.cc_ip = utils.get_ip_of_chromecast(args.chromecast_device)

    if args.override_player:
        args.override_player = shlex.split(args.override_player)

    log.info(utils.dict_filter_bool(args.__dict__))

    args.sock = None
    return args


def chromecast_play(args, m) -> None:
    if args.action in (SC.watch):
        catt_log = player.watch_chromecast(args, m, subtitles_file=externalize_subtitle(m["path"]))
    elif args.action in (SC.listen):
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
            args.play_in_order >= 1 and args.action != SC.listen,
            args.play_in_order >= 0 and args.action == SC.listen and "audiobook" in media_file.lower(),
        ]
    )


def transcode(next_video):
    temp_video = cmd("mktemp", "--suffix=.mkv", "--dry-run").stdout.strip()
    shutil.move(next_video, temp_video)
    next_video = str(Path(next_video).with_suffix(".mkv"))
    cmd(
        f"ffmpeg -nostdin -loglevel error -stats -i {temp_video} -map 0 -scodec webvtt -vcodec h264"
        " -preset fast -profile:v high -level 4.1 -crf 17 -pix_fmt yuv420p"
        " -acodec opus -ac 2 -b:a 128k -filter:a loudnorm=i=-18:lra=17"
        f" {next_video} && rm {temp_video}"
    )
    print(next_video)
    return next_video


def play(args, m: Dict) -> None:
    media_file = m["path"]

    if args.safe and not tube_backend.is_supported(m["path"]):
        log.warning("[%s]: Unsupported URL (safe_mode)", m["path"])
        return

    if is_play_in_order_lvl2(args, media_file):
        media_file = get_ordinal_media(args, media_file)

    if args.action in (SC.watch, SC.listen) and not media_file.startswith("http"):
        media_path = Path(args.prefix + media_file).resolve()
        if not media_path.exists():
            mark_media_deleted(args, media_file)
            log.warning("[%s]: Does not exist. Skipping...", media_file)
            return
        media_file = str(media_path)

        if args.transcode:
            media_file = transcode(media_file)

    if args.action == SC.listen and not media_file.startswith("http"):
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
        return player.socket_play(args, m)

    else:
        r = player.local_player(args, m, media_file)
        if r.returncode != 0:
            print("Player exited with code", r.returncode)
            if args.ignore_errors:
                return
            else:
                raise SystemExit(r.returncode)

    if args.action in (SC.listen, SC.watch):
        player.post_act(args, media_file)


def process_playqueue(args) -> None:
    query, bindings = construct_query(args)

    if args.print:
        player.printer(args, query, bindings)
        return None

    media = list(args.db.query(query, bindings))

    if args.partial and Path(args.watch_later_directory).exists():
        media = utils.mpv_enrich2(args, media)

    if not media:
        utils.no_media_found()

    if all(
        [
            Path(args.watch_later_directory).exists(),
            args.play_in_order == 0,
            "sort" in args.defaults,
            not args.partial,
        ]
    ):
        media = utils.mpv_enrich(args, media)

    if args.multiple_playback:
        player.multiple_player(args, media)
    else:
        try:
            for m in media:
                play(args, m)
        finally:
            if args.interdimensional_cable:
                args.sock.send((f"raw quit \n").encode())
            Path(args.mpv_socket).unlink(missing_ok=True)
            if args.chromecast:
                Path(consts.CAST_NOW_PLAYING).unlink(missing_ok=True)


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
