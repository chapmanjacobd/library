import argparse, shlex, shutil, sys, time
from pathlib import Path
from random import random
from typing import Dict, Tuple

from xklb import consts, db, player, subtitle, tube_backend, utils
from xklb.consts import SC
from xklb.playback import now_playing
from xklb.player import get_ordinal_media, mark_media_deleted, override_sort
from xklb.utils import cmd_interactive, log, random_filename, safe_unpack


def usage(action) -> str:
    return f"""library {action} [database] [optional args]

    Control playback:
        To stop playback press Ctrl-C in either the terminal or mpv

        Create global shortcuts in your desktop environment by sending commands to mpv_socket:
        echo 'playlist-next force' | socat - /tmp/mpv_socket

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

    Filter media by file siblings of parent directory:
        library {action} --sibling   # only include files which have more than or equal to one sibling
        library {action} --solo      # only include files which are alone by themselves

        `--sibling` is just a shortcut for `--lower 2`; `--solo` is `--upper 1`
        library {action} --sibling --solo      # you will always get zero records here
        library {action} --lower 2 --upper 1   # equivalent

        You can be more specific via the `--upper` and `--lower` flags
        library {action} --lower 3   # only include files which have three or more siblings
        library {action} --upper 3   # only include files which have fewer than three siblings
        library {action} --lower 3 --upper 3   # only include files which are three siblings inclusive
        library {action} --lower 12 --upper 25 -OOO  # on my machine this launches My Mister 2018

    Play recent partially-watched videos (requires mpv history):
        library {action} --partial       # play newest first
        library {action} --partial old   # play oldest first
        library {action} -P o            # equivalent
        library {action} -P p            # sort by progress / duration
        library {action} -P s            # skip partially watched (only show unseen)

        The default time used is "last-viewed" (ie. the most recent time you closed the video)
        If you want to use the "first-viewed" time (ie. the very first time you opened the video)
        library {action} -P f            # use watch_later file creation time instead of modified time

        You can combine most of these options, though some will be overridden by others.
        library {action} -P fo           # this means "show the oldest videos using the time I first opened them"

    Print instead of play:
        library {action} --print --limit 10  # print the next 10 files
        library {action} -p -L 10  # print the next 10 files
        library {action} -p  # this will print _all_ the media. be cautious about `-p` on an unfiltered set

        Printing modes
        library {action} -p    # print as a table
        library {action} -p a  # print an aggregate report
        library {action} -p b  # print a bigdirs report (see lb bigdirs -h for more info)
        library {action} -p f  # print fields (defaults to path; use --cols to change)
                               # -- useful for piping paths to utilities like xargs or GNU Parallel

        library {action} -p d  # mark deleted
        library {action} -p w  # mark watched

        Some printing modes can be combined
        library {action} -p df  # print files for piping into another program and mark them as deleted within the db
        library {action} -p bf  # print fields from bigdirs report

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

        Print an aggregate report of media that has no duration information (ie. online or corrupt local media)
        library {action} -w 'duration is null' -p=a

        Print a list of filenames which have below 1280px resolution
        library {action} -w 'width<1280' -p=f

        Print media you have partially viewed with mpv
        library {action} --partial -p
        library {action} -P -p  # equivalent
        library {action} -P -p f --cols path,progress,duration  # print CSV of partially watched files
        library {action} --partial -pa  # print an aggregate report of partially watched files

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
        library {action} --skip 10        # offset ten from the top of an ordered query

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
        library {action} -s '  ost'        # will match OST and not ghost
        library {action} -s toy story      # will match '/folder/toy/something/story.mp3'
        library {action} -s 'toy  story'   # will match more strictly '/folder/toy story.mp3'

        You can search without -s but it must directly follow the database due to how argparse works
        library {action} my.db searching for something

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
        library {action} -S 6  # 6 MB ±10 percent (ie. between 5 and 7 MB)
        library {action} -S-6  # less than 6 MB
        library {action} -S+6  # more than 6 MB

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
        library {action} --post-action keep    # do nothing after playing (default)
        library {action} -k delete             # delete file after playing
        library {action} -k softdelete         # mark deleted after playing

        library {action} -k ask_keep           # ask whether to keep after playing
        library {action} -k ask_delete         # ask whether to delete after playing

        library {action} -k move               # move to "keep" dir after playing
        library {action} -k ask_move           # ask whether to move to "keep" folder
        The default location of the keep folder is ./keep/ (relative to the played media file)
        You can change this by explicitly setting an *absolute* `keep-dir` path:
        library {action} -k ask_move --keep-dir /home/my/music/keep/

        library {action} -k ask_move_or_delete # ask after each whether to move to "keep" folder or delete

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


def parse_args_sort(args) -> None:
    if args.sort:
        args.sort = " ".join(args.sort)
    elif not args.sort and hasattr(args, "defaults"):
        args.defaults.append("sort")

    m_columns = args.db["media"].columns_dict

    # switching between videos with and without subs is annoying
    subtitle_count = "=0"
    if random() < getattr(args, "subtitle_mix", consts.DEFAULT_SUBTITLE_MIX):
        # bias slightly toward videos without subtitles
        subtitle_count = ">0"

    sorts = [
        (getattr(args, "random", False), "random", "random"),
        (args.sort and "rank" in args.sort, args.sort, args.sort),
        ("video_count" in m_columns and args.action == SC.watch, "video_count > 0 desc", "video_count > 0 "),
        ("audio_count" in m_columns, "audio_count > 0 desc", "audio_count > 0"),
        (
            "time_downloaded" in m_columns and "time_downloaded" not in " ".join(sys.argv),
            "time_downloaded > 0 desc",
            "time_downloaded > 0",
        ),
        (True, 'm.path like "http%"', 'm.path like "http%" desc'),
        ("width" in m_columns and hasattr(args, "portrait") and args.portrait, "width < height desc", "width < height"),
        (
            "subtitle_count" in m_columns
            and args.action == SC.watch
            and not any(
                [
                    args.print,
                    consts.PYTEST_RUNNING,
                    "subtitle_count" in args.where,
                    args.limit != consts.DEFAULT_PLAY_QUEUE,
                ],
            ),
            f"subtitle_count {subtitle_count} desc",
            f"subtitle_count {subtitle_count}",
        ),
        (args.sort, args.sort, args.sort),
        (args.action in (SC.listen, SC.watch) and args.include, "duration desc", "duration"),
        (args.action in (SC.listen, SC.watch) and args.include, "size desc", "size"),
        (args.action in (SC.listen, SC.watch) and "play_count" in m_columns, "play_count", "play_count desc"),
        (
            args.action in (SC.listen, SC.watch) and "size" in m_columns and "duration" in m_columns,
            "ntile(1000) over (order by size) desc, duration",
            "ntile(1000) over (order by size), duration desc",
        ),
        (args.action == SC.filesystem, "sparseness", "sparseness desc"),
        (args.action == SC.filesystem, "size", "size desc"),
        (True, "m.path", "m.path desc"),
        (True, "random", "random"),
    ]

    sort = [
        c[2] if args.print and "f" not in args.print and "limit" in getattr(args, "defaults", []) else c[1]
        for c in sorts
        if c[0]
    ]
    sort = list(filter(bool, sort))
    sort = [override_sort(s) for s in sort]
    sort = "\n        , ".join(sort)
    args.sort = sort.replace(",,", ",")


def parse_args(action, default_chromecast=None) -> argparse.Namespace:
    DEFAULT_PLAYER_ARGS_SUB = ["--speed=1"]
    DEFAULT_PLAYER_ARGS_NO_SUB = ["--speed=1.46"]

    parser = argparse.ArgumentParser(prog="library " + action, usage=usage(action))

    parser.add_argument("--play-in-order", "-O", action="count", default=0, help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--random", "-r", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--no-fts", action="store_true")

    parser.add_argument("--created-within", help=argparse.SUPPRESS)
    parser.add_argument("--created-before", help=argparse.SUPPRESS)
    parser.add_argument("--changed-within", "--modified-within", help=argparse.SUPPRESS)
    parser.add_argument("--changed-before", "--modified-before", help=argparse.SUPPRESS)
    parser.add_argument("--played-within", help=argparse.SUPPRESS)
    parser.add_argument("--played-before", help=argparse.SUPPRESS)
    parser.add_argument("--deleted-within", help=argparse.SUPPRESS)
    parser.add_argument("--deleted-before", help=argparse.SUPPRESS)

    parser.add_argument(
        "--chromecast-device",
        "--cast-to",
        "-t",
        default=default_chromecast or "",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--chromecast", "--cast", "-c", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cast-with-local", "-wl", action="store_true", help=argparse.SUPPRESS)
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
    parser.add_argument("--size", "-S", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--duration-from-size", action="append", help=argparse.SUPPRESS)

    parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--moved", nargs=2, help=argparse.SUPPRESS)

    parser.add_argument("--cols", "-cols", "-col", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--skip", "--offset", help=argparse.SUPPRESS)
    parser.add_argument(
        "--partial",
        "-P",
        "--previous",
        "--recent",
        default=False,
        const="n",
        nargs="?",
        help=argparse.SUPPRESS,
    )

    parser.add_argument("--start", "-vs", help=argparse.SUPPRESS)
    parser.add_argument("--end", "-ve", help=argparse.SUPPRESS)
    parser.add_argument("--mpv-socket", default=consts.DEFAULT_MPV_SOCKET, help=argparse.SUPPRESS)
    parser.add_argument("--watch-later-directory", default=consts.DEFAULT_MPV_WATCH_LATER, help=argparse.SUPPRESS)
    parser.add_argument("--subtitle-mix", default=consts.DEFAULT_SUBTITLE_MIX, help=argparse.SUPPRESS)

    parser.add_argument("--override-player", "--player", "-player", help=argparse.SUPPRESS)
    parser.add_argument("--player-args-sub", "-player-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_SUB)
    parser.add_argument("--player-args-no-sub", "-player-no-sub", nargs="*", default=DEFAULT_PLAYER_ARGS_NO_SUB)
    parser.add_argument("--transcode", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--transcode-audio", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--post-action", "--action", "-k", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--keep-dir", "--keepdir", default="keep", help=argparse.SUPPRESS)
    parser.add_argument("--keep-cmd", "--keepcmd", help=argparse.SUPPRESS)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--shallow-organize", default="/mnt/d/", help=argparse.SUPPRESS)

    parser.add_argument("--online-media-only", "--online-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local-media-only", "--local-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")

    parser.add_argument("--sibling", "--episode", action="store_true")
    parser.add_argument("--solo", action="store_true")

    parser.add_argument("--sort-by-deleted", action="store_true")
    parser.add_argument("--depth", "-D", default=0, type=int, help="Depth of folders")
    parser.add_argument("--lower", type=int, help="Number of files per folder lower limit")
    parser.add_argument("--upper", type=int, help="Number of files per folder upper limit")

    parser.add_argument("--timeout", "-T", help=argparse.SUPPRESS)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("search", nargs="*")
    args = parser.parse_intermixed_args()
    args.action = action
    args.defaults = []

    args.include += args.search
    if args.include == ["."]:
        args.include = [str(Path().cwd().resolve())]

    if args.db:
        args.database = args.db
    args.db = db.connect(args)

    if not args.limit:
        args.defaults.append("limit")
        if not any([args.print and len(args.print.replace("p", "")) > 0, args.partial, args.lower, args.upper]):
            if args.action in (SC.listen, SC.watch, SC.read):
                args.limit = consts.DEFAULT_PLAY_QUEUE
            elif args.action in (SC.view):
                args.limit = consts.DEFAULT_PLAY_QUEUE * 4
    elif args.limit in ("inf", "all"):
        args.limit = None

    parse_args_sort(args)

    if args.cols:
        args.cols = list(utils.flatten([s.split(",") for s in args.cols]))

    if args.duration:
        args.duration = utils.parse_human_to_sql(utils.human_to_seconds, "duration", args.duration)

    if args.size:
        args.size = utils.parse_human_to_sql(utils.human_to_bytes, "size", args.size)

    if args.duration_from_size:
        args.duration_from_size = utils.parse_human_to_sql(utils.human_to_bytes, "size", args.duration_from_size)

    if args.chromecast:
        from catt.api import CattDevice

        args.cc = CattDevice(args.chromecast_device, lazy=True)
        args.cc_ip = utils.get_ip_of_chromecast(args.chromecast_device)

    if args.override_player:
        args.override_player = shlex.split(args.override_player)

    log.info(utils.dict_filter_bool(args.__dict__))

    if args.keep_dir:
        args.keep_dir = Path(args.keep_dir).expanduser().resolve()

    if args.solo:
        args.upper = 1
    if args.sibling:
        args.lower = 2

    if args.post_action:
        args.post_action = args.post_action.replace("-", "_")

    utils.timeout(args.timeout)

    args.sock = None
    return args


def construct_search_bindings(args, columns) -> None:
    includes, excludes = db.gen_include_excludes(columns)

    for idx, inc in enumerate(args.include):
        args.filter_sql.append(includes.format(idx))
        args.filter_bindings[f"include{idx}"] = "%" + inc.replace(" ", "%").replace("%%", " ") + "%"
    for idx, exc in enumerate(args.exclude):
        args.filter_sql.append(excludes.format(idx))
        args.filter_bindings[f"exclude{idx}"] = "%" + exc.replace(" ", "%").replace("%%", " ") + "%"


def construct_query(args) -> Tuple[str, dict]:
    m_columns = args.db["media"].columns_dict
    args.filter_sql = []
    args.filter_bindings = {}

    if args.duration:
        args.filter_sql.append(" and duration IS NOT NULL " + args.duration)
    if args.size:
        args.filter_sql.append(" and size IS NOT NULL " + args.size)
    if args.duration_from_size:
        args.filter_sql.append(
            " and size IS NOT NULL and duration in (select distinct duration from m where 1=1 "
            + args.duration_from_size
            + ")",
        )

    args.filter_sql.extend([" and " + w for w in args.where])

    def ii(string):
        if string.isdigit():
            return string + " minutes"
        return string.replace("mins", "minutes").replace("secs", "seconds")

    if args.created_within:
        args.filter_sql.append(
            f"and time_created > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.created_within)}')) as int)",
        )
    if args.created_before:
        args.filter_sql.append(
            f"and time_created < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.created_before)}')) as int)",
        )
    if args.changed_within:
        args.filter_sql.append(
            f"and time_modified > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.changed_within)}')) as int)",
        )
    if args.changed_before:
        args.filter_sql.append(
            f"and time_modified < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.changed_before)}')) as int)",
        )
    if args.played_within:
        args.filter_sql.append(
            f"and time_played > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.played_within)}')) as int)",
        )
    if args.played_before:
        args.filter_sql.append(
            f"and time_played < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.played_before)}')) as int)",
        )
    if args.deleted_within:
        args.filter_sql.append(
            f"and time_deleted > cast(STRFTIME('%s', datetime( 'now', '-{ii(args.deleted_within)}')) as int)",
        )
    if args.deleted_before:
        args.filter_sql.append(
            f"and time_deleted < cast(STRFTIME('%s', datetime( 'now', '-{ii(args.deleted_before)}')) as int)",
        )

    args.table = "media"
    if args.db["media"].detect_fts() and not args.no_fts:
        if args.include:
            args.table = db.fts_search(args)
            m_columns = {**m_columns, "rank": int}
        elif args.exclude:
            construct_search_bindings(args, m_columns)
    else:
        construct_search_bindings(args, m_columns)

    if args.table == "media" and not any(
        [
            args.filter_sql,
            args.where,
            args.print,
            args.partial,
            args.lower,
            args.upper,
            args.limit != consts.DEFAULT_PLAY_QUEUE,
            args.duration_from_size,
        ],
    ):
        limit = 60_000
        if args.random:
            limit = consts.DEFAULT_PLAY_QUEUE * 16

        if "limit" in args.defaults:
            where_not_deleted = (
                "where COALESCE(time_deleted,0) = 0"
                if "time_deleted" in m_columns and "time_deleted" not in " ".join(sys.argv)
                else ""
            )
            args.filter_sql.append(
                f"and m.rowid in (select rowid from media {where_not_deleted} order by random() limit {limit})",
            )

    duration = "duration"
    if args.action == SC.read:
        duration = "cast(length(tags) / 4.2 / 220 * 60 as INT) + 10 duration"

    cols = args.cols or ["path", "title", duration, "size", "subtitle_count", "is_dir", "rank"]
    SELECT = "\n        , ".join([c for c in cols if c in m_columns or c == "*"])
    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    OFFSET = f"OFFSET {args.skip}" if args.skip and args.limit else ""
    query = f"""WITH m as (
    SELECT rowid, * FROM {args.table}
    WHERE 1=1
        {'and path like "http%"' if args.safe else ''}
        {f'and path not like "{args.keep_dir}%"' if Path(args.keep_dir).exists() else ''}
        {'and COALESCE(time_deleted,0) = 0' if 'time_deleted' in m_columns and 'time_deleted' not in ' '.join(sys.argv) else ''}
        {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
        {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
        {'AND COALESCE(time_downloaded,0) = 0' if args.online_media_only else ''}
        {'AND COALESCE(time_downloaded,1)!= 0 AND path not like "http%"' if args.local_media_only else ''}
    )
    SELECT
        {SELECT}
    FROM m
    WHERE 1=1
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        , {args.sort}
    {LIMIT} {OFFSET}
    """

    args.filter_sql = [
        s for s in args.filter_sql if "rowid" not in s
    ]  # only use random rowid constraint in first query

    return query, args.filter_bindings


def chromecast_play(args, m) -> None:
    if args.action in (SC.watch):
        catt_log = player.watch_chromecast(args, m, subtitles_file=safe_unpack(subtitle.get_subtitle_paths(m["path"])))
    elif args.action in (SC.listen):
        catt_log = player.listen_chromecast(args, m)
    else:
        raise NotImplementedError

    if catt_log:
        if catt_log.stderr is None or catt_log.stderr == "":
            if not args.cast_with_local:
                raise RuntimeError("catt does not exit nonzero? but something might have gone wrong")
        elif "Heartbeat timeout, resetting connection" in catt_log.stderr:
            raise RuntimeError("Media is possibly partially unwatched")


def is_play_in_order_lvl2(args, media_file) -> bool:
    return any(
        [
            args.play_in_order >= consts.SIMILAR,
            args.action == SC.listen and "audiobook" in media_file.lower(),
        ],
    )


def transcode(args, path) -> str:
    log.debug(path)
    sub_index = subtitle.get_sub_index(args, path)

    transcode_dest = str(Path(path).with_suffix(".mkv"))
    temp_video = random_filename(transcode_dest)

    maps = ["-map", "0"]
    if sub_index:
        maps = ["-map", "0:v", "-map", "0:a", "-map", "0:" + str(sub_index), "-scodec", "webvtt"]

    video_settings = [
        "-vcodec",
        "h264",
        "-preset",
        "fast",
        "-profile:v",
        "high",
        "-level",
        "4.1",
        "-crf",
        "17",
        "-pix_fmt",
        "yuv420p",
    ]
    if args.transcode_audio:
        video_settings = ["-c:v", "copy"]

    print("Transcoding", temp_video)
    cmd_interactive(
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-stats",
        "-i",
        path,
        *maps,
        *video_settings,
        "-acodec",
        "libopus",
        "-ac",
        "2",
        "-b:a",
        "128k",
        "-filter:a",
        "loudnorm=i=-18:lra=17",
        temp_video,
    )
    Path(path).unlink()
    shutil.move(temp_video, transcode_dest)
    return transcode_dest


def play(args, m: Dict) -> None:
    original_path = m["path"]
    if args.action in (SC.watch, SC.listen) and not m["path"].startswith("http"):
        media_path = Path(args.prefix + m["path"]).resolve() if args.prefix else Path(m["path"])
        m["path"] = str(media_path)

        if not media_path.exists():
            log.warning("[%s]: Does not exist. Skipping...", m["path"])
            mark_media_deleted(args, original_path)
            return

        if args.transcode or args.transcode_audio:
            m["path"] = transcode(args, m["path"])

    print(now_playing(m["path"]))

    args.player = player.parse(args, m)

    start_time = time.time()
    if args.chromecast:
        try:
            chromecast_play(args, m)
        except Exception:
            if args.ignore_errors:
                return
            else:
                raise

    elif args.interdimensional_cable:
        player.socket_play(args, m)
        return

    else:
        r = player.local_player(args, m)
        if r.returncode != 0:
            log.warning("Player exited with code %s", r.returncode)
            if args.ignore_errors:
                return
            else:
                raise SystemExit(r.returncode)

    m_columns = args.db["media"].columns_dict
    if "playhead" in m_columns:
        playhead = utils.get_playhead(
            args,
            original_path,
            start_time,
            existing_playhead=m.get("playhead"),
            media_duration=m.get("duration"),
        )
        if playhead:
            player.set_playhead(args, original_path, playhead)
    player.post_act(args, original_path)


def process_playqueue(args) -> None:
    query, bindings = construct_query(args)

    if args.print and not any([args.partial, args.lower, args.upper, args.safe, args.play_in_order > 0]):
        player.printer(args, query, bindings)
        return

    media = list(args.db.query(query, bindings))

    if args.partial and Path(args.watch_later_directory).exists():
        media = utils.mpv_enrich2(args, media)

    if args.lower is not None or args.upper is not None:
        media = utils.filter_episodic(args, media)

    if not media:
        utils.no_media_found()

    if all(
        [
            Path(args.watch_later_directory).exists(),
            args.play_in_order == 0,
            "sort" in args.defaults,
            not args.partial,
            not args.random,
        ],
    ):
        media = utils.mpv_enrich(args, media)

    if args.safe:
        media = [d for d in media if tube_backend.is_supported(d["path"]) or Path(d["path"]).exists()]

    if args.print:
        if args.play_in_order >= consts.SIMILAR:
            media = [get_ordinal_media(args, d) for d in media]
        player.media_printer(args, media)
    elif args.multiple_playback:
        args.gui = True
        player.multiple_player(args, media)
    else:
        try:
            for m in media:
                if is_play_in_order_lvl2(args, m["path"]):
                    m = get_ordinal_media(args, m)
                play(args, m)
        finally:
            if args.interdimensional_cable:
                args.sock.send(b"raw quit \n")
            Path(args.mpv_socket).unlink(missing_ok=True)
            if args.chromecast:
                Path(consts.CAST_NOW_PLAYING).unlink(missing_ok=True)


def watch() -> None:
    args = parse_args(SC.watch, default_chromecast="Living Room TV")
    process_playqueue(args)


def listen() -> None:
    args = parse_args(SC.listen, default_chromecast="Xylo and Orchestra")
    process_playqueue(args)


def filesystem() -> None:
    args = parse_args(SC.filesystem)
    process_playqueue(args)


def read() -> None:
    args = parse_args(SC.read)
    process_playqueue(args)


def view() -> None:
    args = parse_args(SC.view)
    process_playqueue(args)
