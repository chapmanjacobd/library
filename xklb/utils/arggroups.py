import argparse, os, textwrap
from pathlib import Path

from xklb.utils import (
    arg_utils,
    argparse_utils,
    consts,
    db_utils,
    file_utils,
    iterables,
    nums,
    objects,
    processes,
    sql_utils,
)
from xklb.utils.consts import DEFAULT_FILE_ROWS_READ_LIMIT, DBType
from xklb.utils.log_utils import log


def get_caller_name():
    import inspect

    frame = inspect.currentframe()
    while frame:
        frame = frame.f_back

        if frame is None:
            return "No parse_args()"
        elif frame.f_code.co_name == "parse_args":
            frame = frame.f_back
            return frame.f_code.co_name  # type: ignore


def args_post(args, parser, create_db=False):
    args.ext = [s.lower() for s in args.ext]

    args.defaults = {k: v for k, v in args.__dict__.items() if parser.get_default(k) == v}
    settings = {
        k: v
        for k, v in args.__dict__.items()
        if k not in ["database", "verbose", "defaults"] + list(args.defaults.keys())
    }
    args.extractor_config = {
        k: v for k, v in settings.items() if k not in ["db", "paths", "actions", "backfill_pages"]
    } | (getattr(args, "extractor_config", None) or {})

    log_args = objects.dict_filter_bool(settings)
    if log_args:
        max_v = 140
        log.info(
            {
                k: (
                    v
                    if len(str(v)) < max_v
                    else textwrap.shorten(str(v), max_v, placeholder=f"[{iterables.safe_len(v)} items]")
                )
                for k, v in log_args.items()
            }
        )

    args.action = get_caller_name()

    if create_db:
        Path(args.database).touch()
        args.db = db_utils.connect(args)
    elif getattr(args, "database", False):
        args.db = db_utils.connect(args)

    if getattr(args, "timeout", False):
        processes.timeout(args.timeout)


def printing(parser):
    printing = parser.add_argument_group("Printing")
    printing.add_argument("--to-json", action="store_true", help="Write JSONL to stdout")
    printing.add_argument("--cols", "--columns", nargs="+", help="Include specific column(s) when printing")
    printing.add_argument(
        "--print",
        "-p",
        default="",
        const="p",
        nargs="?",
        help="""Print instead of play

Printing modes
-p    # print as a table
-p a  # print an aggregate report
-p b  # print a big-dirs report (see library bigdirs -h for more info)
-p f  # print fields (defaults to path; useful for piping to utilities like xargs or GNU Parallel)
-p d  # mark deleted
-p w  # mark watched

When a printing mode is explicitly set then all rows will be fetched unless --limit is explicitly set

Some printing modes can be combined
-p df  # print fields for piping into another program and mark as deleted
-p bf  # print fields from big-dirs report""",
    )


def debug(parent_parser):
    parser = parent_parser.add_argument_group("Global options")
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="""Control the level of logging verbosity
-v     # info
-vv    # debug
-vvv   # debug, with SQL query printing
-vvvv  # debug, with external libraries logging""",
    )
    parser.add_argument("--timeout", "-T", metavar="TIME", help="Quit after x minutes")
    parser.add_argument("--threads", type=int, help="Load x files in parallel")
    parser.add_argument("--same-file-threads", type=int, help="Read the same file x times in parallel")
    parser.add_argument(
        "--ext", "-e", default=[], action=argparse_utils.ArgparseList, help="Include only specific file extensions"
    )
    parser.add_argument("--simulate", "--dry-run", action="store_true")
    printing(parent_parser)


def capability_soft_delete(parent_parser):
    parser = parent_parser.add_argument_group("Modify Metadata")
    parser.add_argument(
        "--mark-deleted", "--soft-delete", action="store_true", help="Mark matching rows as deleted (soft-delete)"
    )
    parser.add_argument("--mark-watched", action="store_true", help="Mark matching rows as watched")
    parser.add_argument("--delete-rows", action="store_true", help="Delete matching rows from database table")


def capability_delete(parent_parser):
    parser = parent_parser.add_argument_group("Delete Files")
    parser.add_argument(
        "--override-trash", "--override-rm", "--trash-cmd", default="trash", help="Custom trash command"
    )
    parser.add_argument(
        "--delete-files",
        "--trash",
        "--rm",
        action="store_true",
        help="Delete matching files from filesystem",
    )


def database(parent_parser):
    parser = parent_parser.add_argument_group("Database")
    capability_soft_delete(parent_parser)
    capability_delete(parent_parser)
    parser.add_argument("--db", "-db", help="Positional argument override")
    parser.add_argument("database")


def paths_or_stdin(parent_parser, destination=False):
    parser = parent_parser.add_argument_group("Paths")
    parser.add_argument(
        "--from-file",
        "--from-text",
        "--file",
        action="store_true",
        help="Read paths from line-delimited file(s)",
    )
    parser.add_argument("--from-json", "--json", action="store_true", help="Read JSON or JSONL from stdin")
    if destination:
        parser.add_argument("paths", nargs="+", action=argparse_utils.ArgparseArgsOrStdin)
    else:
        parser.add_argument(
            "paths", nargs="*", default=argparse_utils.STDIN_DASH, action=argparse_utils.ArgparseArgsOrStdin
        )


def sql_fs(parent_parser):
    parse_fs = parent_parser.add_argument_group("FileSystemDB SQL")
    parse_fs.add_argument(
        "--limit",
        "--queue",
        "-n",
        "-l",
        "-L",
        help="""Set play queue size
-L inf  # no limit
-L 10   # 10 files
(default: 120 media, 480 images, 7 links, 7200 downloads)""",
    )
    parse_fs.add_argument(
        "--offset",
        help="""Skip files which would have been in the queue
--offset 10  # skip 10 files""",
    )
    parse_fs.add_argument(
        "--sort",
        "-u",
        nargs="+",
        default=[],
        help="""Choose media play order
--sort duration   # play shortest media first
-u duration desc  # play longest media first

You can use multiple SQL ORDER BY expressions
-u 'subtitle_count > 0 desc' # play media that has at least one subtitle first

Prioritize large-sized media
--sort 'ntile(10000) over (order by size/duration) desc'
-u 'ntile(100) over (order by size) desc'

Sort by count of media with the same-X column (default DESC: most common to least common value)
-u same-duration
-u same-title
-u same-size
-u same-width, same-height ASC, same-fps
-u same-time_uploaded same-view_count same-upvote_ratio""",
    )
    parse_fs.add_argument(
        "--random",
        "-r",
        action="store_true",
        help="Sort by random and use performance hacks to make SQLite faster for large databases",
    )

    parse_fs.add_argument("--playlists", nargs="+", action="extend", default=[], help="Include media by playlist URLs")

    parse_fs.add_argument(
        "--where",
        "-w",
        nargs="+",
        action="extend",
        default=[],
        help="""Constrain media by arbitrary SQL expressions
--where audio_count = 2  # media which have two audio tracks
-w "language = 'eng'"    # media which have an English language tag (this could be audio _or_ subtitle)
-w subtitle_count=0      # media that doesn't have subtitles""",
    )
    parse_fs.add_argument("--fts", action=argparse.BooleanOptionalAction, default=True, help="Full Text Search mode")
    parse_fs.add_argument(
        "--include",
        "--search",
        "-s",
        nargs="+",
        action="extend",
        default=[],
        help="""Include files via search
-s happy  # path, title, or tags must match "happy"

In --fts mode (default):

Use fts syntax to search specific columns:
-s 'path : mad max'
-s "path : 'mad max'" # add "quotes" to be more strict

In --no-fts mode:

Use --where to search specific columns:
--no-fts -w 'path like "%%happy%%"'

Double spaces are equal to one space:
--no-fts -s "  ost"        # will match OST and not ghost
--no-fts -s toy story      # will match '/folder/toy/something/story.mp3'
--no-fts -s "toy  story"   # will match more strictly '/folder/toy story.mp3'""",
    )
    parse_fs.add_argument(
        "--exclude",
        "-E",
        nargs="+",
        action="extend",
        default=[],
        help="""Exclude files via search
-E sad  # path, title, or tags must not match "sad"
-w 'path not like "%%sad%%"'""",
    )
    parse_fs.add_argument(
        "--exact",
        action="store_true",
        help="""Not useful except when searching paths and excluding subpaths
-s https://files/2024/ --exact  # when you want to match the folder but not its contents""",
    )
    parse_fs.add_argument(
        "--flexible-search",
        "--or",
        "--flex",
        action="store_true",
        help="""Allow results which match only one search term
-s one two --or  # results will include /one/file.mkv and /two/file.mka
-s one two       # results will only include /one/two.mkv""",
    )

    parse_fs.add_argument("--online-media-only", "--online", action="store_true", help="Exclude local media")
    parse_fs.add_argument("--local-media-only", "--local", action="store_true", help="Exclude online media")

    parse_fs.add_argument(
        "--sizes",
        "-S",
        action="append",
        help="""Constrain media to file sizes (uses the same syntax as fd-find)
-S 6           # 6 MB exactly (not likely)
-S-6           # less than 6 MB
-S+6           # more than 6 MB
-S 6%%10       # 6 MB ±10 percent (between 5 and 7 MB)
-S+5GB -S-7GB  # between 5 and 7 GB""",
    )
    parse_fs.add_argument(
        "--bitrates",
        "-b",
        action="append",
        help="""Constrain media to bitrates
-b 6           # 6 Mbps exactly (not likely)
-b-6           # less than 6 Mbps
-b+6           # more than 6 Mbps
-b 6%%10       # 6 Mbps ±10 percent (between 5 and 7 Mbps)
-b+50KB -b-700KB  # between 50 and 700 kbit/s""",
    )

    parse_fs.add_argument(
        "--created-within",
        help="""Constrain media by time_created (newer than)
--created-within '3 days'""",
    )
    parse_fs.add_argument(
        "--created-before",
        help="""Constrain media by time_created (older than)
--created-before '3 years'""",
    )
    parse_fs.add_argument(
        "--changed-within",
        "--modified-within",
        help="""Constrain media by time_modified (newer than)
--changed-within '3 days'""",
    )
    parse_fs.add_argument(
        "--changed-before",
        "--modified-before",
        help="""Constrain media by time_modified (older than)
--changed-before '3 years'""",
    )
    parse_fs.add_argument(
        "--deleted-within",
        help="""Constrain media by time_deleted (newer than)
--deleted-within '3 days'""",
    )
    parse_fs.add_argument(
        "--deleted-before",
        help="""Constrain media by time_deleted (older than)
--deleted-before '3 years'""",
    )
    parse_fs.add_argument(
        "--downloaded-within",
        help="""Constrain media by time_downloaded (newer than)
--downloaded-within '3 days'""",
    )
    parse_fs.add_argument(
        "--downloaded-before",
        help="""Constrain media by time_downloaded (older than)
--downloaded-before '3 years'""",
    )

    parse_media = parent_parser.add_argument_group("MediaDB SQL")
    parse_media.add_argument(
        "--portrait",
        action="store_true",
        help="""Constrain media to portrait orientation video
-w 'width<height' # equivalent""",
    )
    parse_media.add_argument("--no-video", "-vn", action="store_true", help="Exclude media which have videos streams")
    parse_media.add_argument("--no-audio", "-an", action="store_true", help="Exclude media which have audio streams")
    parse_media.add_argument(
        "--no-subtitles",
        "--no-subtitle",
        "--no-subs",
        "--nosubs",
        "-sn",
        action="store_true",
        help="Exclude media which have subtitle streams",
    )
    parse_media.add_argument(
        "--subtitles", "--subtitle", "-sy", action="store_true", help="Include only media which have subtitle streams"
    )

    parse_media.add_argument(
        "--played-within",
        help="""Constrain media by time_last_played (newer than)
--played-within '3 days'""",
    )
    parse_media.add_argument(
        "--played-before",
        help="""Constrain media by time_last_played (older than)
--played-before '3 years'""",
    )

    parse_media.add_argument(
        "--partial",
        "-P",
        "--previous",
        "--recent",
        default=False,
        const="n",
        nargs="?",
        help="""Play recent partially-watched videos
--partial       # play newest first
--partial old   # play oldest first
-P o            # equivalent

-P p            # sort by percent remaining
-P t            # sort by time remaining
-P s            # skip partially watched (only show unseen)

The default time used is "last-viewed" (ie. the most recent time you closed the video)
If you want to use the "first-viewed" time (ie. the very first time you opened the video)
-P f            # use watch_later file creation time instead of modified time

You can combine most of these options, though some will override others
-P fo           # using the time you first played, play the oldest videos first
-P pt           # weighted remaining (percent * time remaining)

Print media you have partially viewed with mpv
--partial -p
-P -p          # equivalent
--partial -pa  # print an aggregate report of partially watched files""",
    )

    parse_media.add_argument(
        "--duration",
        "-d",
        action="append",
        help="""Constrain media to duration
-d 6       # 6 mins exactly
-d-6       # less than 6 mins
-d+6       # more than 6 mins
-d 6%%10    # 6 mins ±10 percent (between 5 and 7 mins)
-d+5 -d-7  # between 5 and 7 mins""",
    )
    parse_media.add_argument(
        "--duration-from-size",
        action="append",
        help="""Constrain media to duration of videos which match any size constraints
--duration-from-size +3300MB -u 'duration desc, size desc'""",
    )


def sql_fs_post(args, table_prefix="m.") -> None:
    if args.to_json:
        args.print = "p"

    args.include += getattr(args, "search", [])
    if len(args.include) == 1:
        if args.include == ["."]:
            args.include = [str(Path().cwd().resolve())]
        elif os.sep in args.include[0]:
            args.include[0] = file_utils.resolve_absolute_path(args.include[0])

    arg_utils.parse_args_limit(args)

    pl_columns = db_utils.columns(args, "playlists")
    args.playlists_sort, args.playlists_select = arg_utils.parse_args_sort(args, pl_columns)
    m_columns = db_utils.columns(args, "media")
    args.sort, args.select = arg_utils.parse_args_sort(args, m_columns)

    if args.sizes:
        args.sizes = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", args.sizes)
    if args.bitrates:
        args.bitrates = sql_utils.parse_human_to_sql(nums.human_to_bits, "size*8/duration", args.bitrates)

    if args.cols:
        args.cols = list(iterables.flatten([s.split(",") for s in args.cols]))

    args.filter_sql = []
    args.aggregate_filter_sql = []
    args.filter_bindings = {}

    aggregate_filter_columns = ["time_first_played", "time_last_played", "play_count", "playhead"]
    args.filter_sql.extend(" AND " + w for w in args.where if not any(a in w for a in aggregate_filter_columns))
    args.aggregate_filter_sql.extend(" AND " + w for w in args.where if any(a in w for a in aggregate_filter_columns))

    args.filter_sql.extend(f" AND path like '%.{ext}'" for ext in args.ext)

    if (
        "time_deleted" in m_columns
        and "deleted" not in (getattr(args, "sort_groups_by", None) or "")
        and "time_deleted" not in " ".join(args.where)
    ):
        args.filter_sql.append(f"AND COALESCE({table_prefix}time_deleted,0) = 0")

    if args.local_media_only:
        args.filter_sql.append('AND path not LIKE "http%"')
        if "time_downloaded" in m_columns:
            args.filter_sql.append("AND COALESCE(time_downloaded,1) != 0")

    if args.online_media_only:
        args.filter_sql.append('AND path LIKE "http%"')
        if "time_downloaded" in m_columns:
            args.filter_sql.append("AND COALESCE(time_downloaded,0) = 0")

    if args.sizes:
        args.filter_sql.append(" and size IS NOT NULL " + args.sizes)
    if args.bitrates:
        args.filter_sql.append(" and size IS NOT NULL " + args.bitrates)

    if args.created_within:
        args.filter_sql.append(
            f"and time_created >= cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.created_within)}')) as int)",
        )
    if args.created_before:
        args.filter_sql.append(
            f"and time_created < cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.created_before)}')) as int)",
        )
    if args.changed_within:
        args.filter_sql.append(
            f"and time_modified >= cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.changed_within)}')) as int)",
        )
    if args.changed_before:
        args.filter_sql.append(
            f"and time_modified < cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.changed_before)}')) as int)",
        )
    if args.deleted_within:
        args.filter_sql.append(
            f"and time_deleted >= cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.deleted_within)}')) as int)",
        )
    if args.deleted_before:
        args.filter_sql.append(
            f"and time_deleted < cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.deleted_before)}')) as int)",
        )
    if args.downloaded_within:
        args.filter_sql.append(
            f"and time_downloaded >= cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.downloaded_within)}')) as int)",
        )
    if args.downloaded_before:
        args.filter_sql.append(
            f"and time_downloaded < cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.downloaded_before)}')) as int)",
        )

    if getattr(args, "keep_dir", False) and Path(args.keep_dir).exists():
        args.keep_dir = Path(args.keep_dir).expanduser().resolve()
        args.filter_sql.append(f'and path not like "{args.keep_dir}%"')

    if args.no_video:
        args.filter_sql.append(" and video_count=0 ")
    if args.no_audio:
        args.filter_sql.append(" and audio_count=0 ")
    if args.subtitles:
        args.filter_sql.append(" and subtitle_count>0 ")
    if args.no_subtitles:
        args.filter_sql.append(" and subtitle_count=0 ")

    if args.played_within:
        args.aggregate_filter_sql.append(
            f"and time_last_played >= cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.played_within)}')) as int) ",
        )
    if args.played_before:
        args.aggregate_filter_sql.append(
            f"and time_last_played < cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.played_before)}')) as int) ",
        )

    if args.partial:
        args.aggregate_filter_sql.append(
            "AND COALESCE(time_first_played,0) = 0 " if "s" in args.partial else "AND time_first_played>0 "
        )

    if args.duration:
        args.duration = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", args.duration)
        args.filter_sql.append(" and duration IS NOT NULL " + args.duration)

    if args.duration_from_size:
        args.duration_from_size = sql_utils.parse_human_to_sql(nums.human_to_bytes, "size", args.duration_from_size)
        args.filter_sql.append(
            " and size IS NOT NULL and duration in (select distinct duration from media where 1=1 "
            + args.duration_from_size
            + ")",
        )


def playback(parent_parser):
    parser = parent_parser.add_argument_group("Playback")
    parser.add_argument(
        "--crop",
        "--zoom",
        "--stretch",
        "--fit",
        "--fill",
        action="store_true",
        help="Crop video to fill window (useful with multiple-playback)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop media after reaching end (useful for curation activities like multiple-playback)",
    )
    parser.add_argument("--fullscreen", "--fs", action=argparse.BooleanOptionalAction, help="Open videos in fullscreen")
    parser.add_argument("--pause", action="store_true", help="Start media paused")
    parser.add_argument(
        "--start",
        "-vs",
        help="""Start media at a specific time
--start 35%%  # start media playback at the time of 35%% of duration; wadsworth constant""",
    )
    parser.add_argument(
        "--end",
        "-ve",
        help="""Stop media at a specific time
--end 60%%  # stop media playback at the time of 60%% of duration; avogadro constant""",
    )
    parser.add_argument("--volume", type=float, help="Set volume level before playing")

    parser.add_argument("--mpv-socket", help="Use a custom mpv socket location")
    parser.add_argument(
        "--auto-seek",
        action="store_true",
        help="""Seek playback automatically
Experimental; does not work with --multiple-playback
--auto-seek --player='mpv --pause=yes --loop=yes --start=35%%'

DEPRECIATED: do instead:
function repeatdelay
    while $argv[2..-1]
        and sleep $argv[1]
    end
end
repeatdelay 1.1 xdotool key o
where 'o' is a key that seeks the amount you want in mpv""",
    )

    parser.add_argument(
        "--override-player",
        "--player",
        help='''Use a specific player
--player "vlc --vlc-opts"''',
    )
    parser.add_argument(
        "--ignore-errors",
        "--ignoreerrors",
        "-i",
        action="store_true",
        help="Continue to the next track after a playback error (eg. YouTube video deleted)",
    )

    parser.add_argument(
        "--prefetch", type=int, default=3, help="Prepare for playback by reading some file metadata before it is needed"
    )
    parser.add_argument(
        "--prefix", default="", help="Add a prefix for file paths; eg. SSHFS mount makes paths different from normal"
    )

    parser.add_argument("--folders", "--folder", action="store_true", help="Experimental escape hatch to open folder")
    parser.add_argument(
        "--folder-glob",
        "--folderglob",
        type=int,
        default=False,
        const=10,
        nargs="?",
        help="Experimental escape hatch to open a folder glob limited to x number of files",
    )


def playback_post(args):
    from shlex import split

    if args.override_player:
        args.override_player = split(args.override_player)


def post_actions(parent_parser):
    parser = parent_parser.add_argument_group("Post-Playback Actions")
    parser.add_argument(
        "--exit-code-confirm",
        action="store_true",
        help="Use exit code bifurcation (exit 0=yes vs exit 1=no) instead of asking confirmation for a post-action in the CLI or GUI",
    )
    parser.add_argument("--gui", action="store_true", help="Ask post-action confirmation in a GUI")
    parser.add_argument("--keep-dir", "--keepdir", help='ask_move: move "kept" files to this special folder')
    parser.add_argument(
        "--post-action",
        "--action",
        "-k",
        default="keep",
        help="""Post-actions -- choose what to do after playing
--post-action keep    # do nothing after playing (default)
-k delete             # delete file after playing
-k softdelete         # mark deleted after playing

-k ask_keep           # ask whether to keep after playing
-k ask_delete         # ask whether to delete after playing

-k move               # move to "keep" dir after playing
-k ask_move           # ask whether to move to "keep" folder --keep-dir "/home/my/music/keep/"
                        (default: './keep/' -- relative to the played media file)
-k ask_move_or_delete # ask after each whether to move to "keep" folder or delete

You can also bind keys in mpv to different exit codes. For example in input.conf:
    ; quit 5

And if you run something like:
    --cmd5 ~/bin/process_audio.py {} # this runs the command as a daemon replacing {} with the media file
    --cmd5 echo                      # this does nothing except skip normal post-actions
    --cmd130 exit_multiple_playback  # this will close all videos, even if --ignore-errors is set

When semicolon is pressed in mpv (it will exit with error code 5) then the applicable player-exit-code command
will start with the media file as the first argument; in this case `~/bin/process_audio.py $path`.
The command will be daemonized if library exits before it completes.

To prevent confusion, normal post-actions will be skipped if the exit-code is greater than 4.
Exit-codes 0, 1, 2, 3, and 4: the external post-action will run after normal post-actions. Be careful of conflicting player-exit-code command and post-action behavior when using these!""",
    )


def post_actions_post(args):
    if args.post_action:
        args.post_action = args.post_action.replace("-", "_")


def multiple_playback(parent_parser):
    parser = parent_parser.add_argument_group("Multiple Playback")
    parser.add_argument(
        "--multiple-playback",
        "-m",
        default=False,
        nargs="?",
        const=consts.DEFAULT_MULTIPLE_PLAYBACK,
        type=int,
        help="""Play multiple files at the same time
--multiple-playback    # one per display; or two if only one display detected
--multiple-playback 4  # play four media at once, divide by available screens
-m 4 --screen-name eDP # play four media at once on specific screen
-m 4 --loop --crop     # play four cropped videos on a loop
-m 4 --hstack          # use hstack style

When using `--multiple-playback` it may be helpful to set simple window focus rules to prevent keys from accidentally being entered in the wrong mpv window (as new windows are created and capture the cursor focus).
You can set and restore your previous mouse focus setting by wrapping the command like this:

    focus-under-mouse
    library watch ... --multiple-playback 4
    focus-follows-mouse

For example in KDE:

    function focus-under-mouse
        kwriteconfig5 --file kwinrc --group Windows --key FocusPolicy FocusUnderMouse
        qdbus-qt5 org.kde.KWin /KWin reconfigure
    end

    function focus-follows-mouse
        kwriteconfig5 --file kwinrc --group Windows --key FocusPolicy FocusFollowsMouse
        kwriteconfig5 --file kwinrc --group Windows --key NextFocusPrefersMouse true
        qdbus-qt5 org.kde.KWin /KWin reconfigure
    end""",
    )
    parser.add_argument("--screen-name", help="Playback on a specific display")
    parser.add_argument("--hstack", action="store_true", help="Force videos to stack horizontally")
    parser.add_argument("--vstack", action="store_true", help="Force videos to stack vertically")


def multiple_playback_post(args):
    if args.multiple_playback > 1:
        args.gui = True

        if "fullscreen" in args.defaults:
            args.fullscreen = False


def extractor(parent_parser):
    parser = parent_parser.add_argument_group("Extractor")
    parser.add_argument("--no-sanitize", action="store_true", help="Don't sanitize some common URL parameters")
    parser.add_argument(
        "--insert-only", "--no-extract", "--skip-extract", action="store_true", help="Insert paths into media table"
    )  # TODO: move to its own subcommand
    parser.add_argument(
        "--insert-only-playlists",
        "--insert-only-playlist",
        "--no-extract-playlists",
        "--skip-extract-playlists",
        action="store_true",
        help="Insert paths into playlists table",
    )
    parser.add_argument("--extra", action="store_true", help="Get full metadata (takes a lot longer)")


def extractor_post(args):
    from xklb.utils.path_utils import sanitize_url

    if hasattr(args, "paths"):
        args.paths = list({s.strip() for s in args.paths})
        if not args.no_sanitize:
            args.paths = [sanitize_url(args, p) for p in args.paths]
        args.paths = iterables.conform(args.paths)


def group_folders(parent_parser):
    parser = parent_parser.add_argument_group("Group Folders")
    parser.add_argument(
        "--big-dirs",
        "--bigdirs",
        "-B",
        action="count",
        default=0,
        help="""Group media by folders
Recommended to use with -L inf and --duration or --depth filters; see `lb big-dirs -h` for more info""",
    )

    parser.add_argument(
        "--sibling", "--episode", "--episodic", action="store_true", help="Shorthand for --folder-counts '>1'"
    )
    parser.add_argument("--solo", action="store_true", help="Shorthand for --folder-counts=1")

    parser.add_argument(
        "--sort-groups-by",
        "--sort-groups",
        "--sort-by",
        nargs="+",
        help="""

--sort-groups-by 'mcda median_size,-deleted'  # sort by auto-MCDA""",
    )
    parser.add_argument("--depth", "-D", type=int, help="Folder depth of files")
    parser.add_argument("--parents", action="store_true", help="Include recursive sub-files in folder statistics")

    parser.add_argument(
        "--folder-sizes",
        "--foldersizes",
        "-FS",
        action="append",
        help="Only include folders of specific sizes (uses the same syntax as fd-find)",
    )
    parser.add_argument(
        "--folder-counts",
        "--files-counts",
        "--file-counts",
        "--files",
        "--counts",
        "--episodes",
        "-FC",
        action="append",
        help="""Number of files per folder

-FC=-3  # fewer than 3 siblings
-FC=+3  # more than 3 siblings

-FC=3  # exactly three siblings inclusive
-FC=+3 -FC=-3  # exactly three siblings inclusive

-FC=+12 -FC=-25  # between 12 and 25 files
-FC=5%%20  # 5 siblings ±20%% (4 to 6 siblings)""",
    )
    parser.add_argument("--folders-counts", action="append", help="Number of folders per folder")


def group_folders_post(args) -> None:
    if args.solo:
        args.folder_counts = ["1"]
    if args.sibling:
        args.folder_counts = ["+2"]

    if args.folder_sizes:
        args.folder_sizes = sql_utils.parse_human_to_lambda(nums.human_to_bytes, args.folder_sizes)
    if args.folder_counts:
        args.folder_counts = sql_utils.parse_human_to_lambda(int, args.folder_counts)
    if args.folders_counts:
        args.folders_counts = sql_utils.parse_human_to_lambda(int, args.folders_counts)

    if args.sort_groups_by:
        args.sort_groups_by = arg_utils.parse_ambiguous_sort(args.sort_groups_by)
        args.sort_groups_by = ",".join(args.sort_groups_by)


def cluster(parent_parser):
    parser = parent_parser.add_argument_group("Cluster")
    parser.add_argument("--cluster-sort", "--cluster", "-C", action="store_true", help="Cluster by filename TF-IDF")
    parser.add_argument("--clusters", "--n-clusters", type=int, help="Number of KMeans clusters")
    parser.add_argument(
        "--stop-words",
        "--ignore-words",
        nargs="+",
        action="extend",
        help="""Override the default "stop-word" list to ignore specific words
--stop-words the fox jumps over the moon
--stop-words (cat stop_words.txt)""",
    )

    parser.add_argument("--print-groups", "--groups", "-g", action="store_true", help="Print groups")
    parser.add_argument("--move-groups", "-M", action="store_true", help="Move groups into subfolders")

    parser.add_argument("--near-duplicates", "--similar-only", action="store_true", help="Re-group by difflib ratio")
    parser.add_argument(
        "--unique-only", action="store_true", help="Include only 'unique' lines (not including originals or duplicates)"
    )
    parser.add_argument("--exclude-unique", "--no-unique", action="store_true", help="Exclude 'unique' lines")


def related(parser):
    parser.add_argument(
        "--related",
        "-R",
        action="count",
        default=0,
        help="""Find media related to the first result
--related  # Use fts to find similar content
-R         # equivalent
-RR        # above, plus ignores most filters""",
    )


class FileOverFileOptional:
    DELETE_DEST_HASH = "delete-dest-hash"
    DELETE_DEST_SIZE = "delete-dest-size"
    DELETE_DEST_LARGER = "delete-dest-larger"
    DELETE_DEST_SMALLER = "delete-dest-smaller"
    DELETE_SRC_HASH = "delete-src-hash"
    DELETE_SRC_SIZE = "delete-src-size"
    DELETE_SRC_LARGER = "delete-src-larger"
    DELETE_SRC_SMALLER = "delete-src-smaller"


class FileOverFile:
    SKIP = "skip"
    RENAME_SRC = "rename-src"
    RENAME_DEST = "rename-dest"
    DELETE_SRC = "delete-src"
    DELETE_DEST = "delete-dest"
    DELETE_DEST_ASK = "delete-dest-ask"


class FileOverFolder:
    SKIP = "skip"
    RENAME_SRC = "rename-src"
    RENAME_DEST = "rename-dest"
    DELETE_SRC = "delete-src"
    DELETE_DEST = "delete-dest"
    MERGE = "merge"


class FolderOverFile:
    SKIP = "skip"
    RENAME_DEST = "rename-dest"
    DELETE_SRC = "delete-src"
    DELETE_DEST = "delete-dest"
    MERGE = "merge"


def file_over_file(value):
    parts = value.split()
    if not parts:
        raise argparse.ArgumentTypeError("--file-over-file should have one or more parts separated by a space")

    required_opts = objects.class_enum(FileOverFile)
    optional_opts = objects.class_enum(FileOverFileOptional)

    optionals, required = parts[:-1], parts[-1]

    for opt in optionals:
        if opt not in optional_opts:
            raise argparse.ArgumentTypeError(
                f"Invalid optional conflict resolution option. Choose ZERO OR MORE: {', '.join(optional_opts)}"
            )

    if required not in required_opts:
        raise argparse.ArgumentTypeError(
            f"Invalid required conflict resolution option. Choose ONE: {', '.join(required_opts)}"
        )

    return parts


def clobber(parent_parser):
    parser = parent_parser.add_argument_group("Replace Files")
    parser.add_argument("--bsd", "--rsync", action="store_true", help="BSD trailing slash behavior")
    parser.add_argument("--parent", action="store_true", help="Include parent (dirname) when merging")
    parser.add_argument(
        "--file-over-file",
        type=file_over_file,
        metavar="[action-if ...] fallback",
        default="delete-src-hash rename-src",
        help="""Specify the conflict resolution strategy for file on file clobbering

In this scenario you have a file with the same name as a file in the target directory:

file1.zip (existing file)
file1.zip (new file)

Choose ZERO OR MORE of the following options:
  delete-dest-hash     will delete the existing file if the SHA-256 hash matches
  delete-dest-size     will delete the existing file if the file size matches
  delete-dest-larger   will delete the existing file if it is larger
  delete-dest-smaller  will delete the existing file if it is smaller

  If you trust your target is more recent than the source(s):
  delete-src-hash      will delete the src file if the SHA-256 file hash matches
  delete-src-size      will delete the src file if the file size matches
  delete-src-larger    will delete the src file if it is larger
  delete-src-smaller   will delete the src file if it is smaller

Choose ONE of the following required fallback options:
  skip             will skip the src file
  rename-dest      will rename the existing file to file1_1.zip
  delete-dest      will delete the existing file
  delete-dest-ask  will delete the existing file if confirmed for the specific file

  If you trust your target is more recent than the source(s):
  rename-src       will rename the src file to file1_1.zip
  delete-src       will delete the src file

If you use both an delete-src* option and an delete-dest* option then both src and dest could be deleted!""",
    )
    parser.add_argument(
        "--file-over-folder",
        choices=objects.class_enum(FileOverFolder),
        default="merge",
        help="""Specify the conflict resolution strategy for file on folder clobbering

In this scenario you have a file with the same name as a folder in the target directory:

folder1.zip/ (existing folder)
folder1.zip  (new file)

Choose ONE of the following options:
  skip         will skip the src file
  rename-src   will rename the src file to folder1_1.zip
  rename-dest  will rename the existing folder to folder1_1.zip/
  delete-src   will delete the src file
  delete-dest  will delete the existing folder tree
  merge        will move the src file to folder1.zip/folder1.zip""",
    )
    parser.add_argument(
        "--folder-over-file",
        choices=objects.class_enum(FolderOverFile),
        default="merge",
        help="""Specify the conflict resolution strategy for folder on file clobbering

In this scenario you have a file with the same name as a folder somewhere in the target folder hierarchy:

en.wikipedia.org/wiki                       (existing file)
en.wikipedia.org/wiki/Telescopes/index.html (new folder + files)

Choose ONE  the following options:
  skip         will skip the src files within wiki/
  rename-dest  will rename the existing file to wiki_1
  delete-src   will delete the src folder tree
  delete-dest  will delete the existing file
  merge        will move the existing file to en.wikipedia.org/wiki/wiki""",
    )


def process_ffmpeg(parent_parser):
    parser = parent_parser.add_argument_group("FFMPEG Processing")
    parser.add_argument(
        "--delete-unplayable", action="store_true", help="Delete from disk any media which does not open with ffprobe"
    )

    parser.add_argument(
        "--delete-no-video", action="store_true", help="Delete files with no video instead of extracting audio"
    )
    parser.add_argument(
        "--delete-no-audio", action="store_true", help="Delete files with no audio instead of transcoding video"
    )

    parser.add_argument("--max-height", type=int, default=960)
    parser.add_argument("--max-width", type=int, default=1440)
    parser.add_argument(
        "--max-width-buffer",
        type=float,
        default=0.2,
        help="""Don't resize videos if their width is within a certain percentage of the max-width
--max-width-buffer 0.1  # within 10%% (if --max-width=1440 then anything smaller than 1584px video will be transcoded but not resized)""",
    )
    parser.add_argument(
        "--max-height-buffer",
        type=float,
        default=0.2,
        help="""Don't resize videos if their height is within a certain percentage of the max-height
--max-height-buffer 0.1  # within 10%% (if --max-height=960 then anything shorter than 1056px video will be transcoded but not resized)""",
    )

    parser.add_argument(
        "--always-split",
        "--force-split",
        action="store_true",
        help="Split all video/audio files using silence in audio track",
    )
    parser.add_argument(
        "--split-longer-than",
        help="""Only split on silence for files longer than a specific duration
--split-longer-than 37mins""",
    )
    parser.add_argument(
        "--min-split-segment",
        default=consts.DEFAULT_MIN_SPLIT,
        help="Combine segments that are smaller than this length of time",
    )

    parser.add_argument("--keyframes", action="store_true", help="Only keep keyframes")
    parser.add_argument("--audio-only", action="store_true", help="Only extract audio")
    parser.add_argument(
        "--no-preserve-video",
        action="store_true",
        help="If using --audio-only delete source files even if they have video streams",
    )

    parser.add_argument("--max-image-height", type=int, default=2400)
    parser.add_argument("--max-image-width", type=int, default=2400)

    parser.add_argument("--preset", default="7")
    parser.add_argument("--crf", default="40")


def process_ffmpeg_post(args):
    args.split_longer_than = nums.human_to_seconds(args.split_longer_than)
    args.min_split_segment = nums.human_to_seconds(args.min_split_segment)


def download(parent_parser):
    parser = parent_parser.add_argument_group("Download")
    parser.add_argument(
        "--extractor-config",
        nargs=1,
        action=argparse_utils.ArgparseDict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default extractor/downloader configuration",
    )
    parser.add_argument("--download-archive", help="yt-dlp download archive location (--video,--audio only)")
    parser.add_argument(
        "--extract-audio-ext",
        default="opus",
        help="""Custom file extension to convert to after download
--extract-audio-ext mp3""",
    )

    parser.add_argument(
        "--ignore-errors",
        "--ignoreerrors",
        "-i",
        action="store_true",
        help="Ignore some types of download errors (do not use this blindly!)",
    )
    parser.add_argument("--safe", action="store_true", help="Download only from known domains; skip generic URLs")

    parser.add_argument(
        "--retry-delay",
        default="14 days",
        help="Must be specified in SQLITE Modifiers format: N seconds, minutes, hours, days, months, or years",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fetch metadata for paths even if they are already in the media table",
    )


def download_subtitle(parent_parser):
    parser = parent_parser.add_argument_group("Subtitle Download")
    parser.add_argument("--subs", action="store_true", help="Download and embed subtitles")
    parser.add_argument("--auto-subs", "--autosubs", action="store_true", help="Prefer machine-translated subtitles")
    parser.add_argument(
        "--subtitle-languages",
        "--subtitle-language",
        "--sl",
        action=argparse_utils.ArgparseList,
        help="Download specific subtitle languages",
    )


def table_like(parent_parser):
    parser = parent_parser.add_argument_group("Table-like")
    parser.add_argument(
        "--mimetype",
        "--filetype",
        help="""Treat given files as having a specific file type
--filetype csv""",
    )
    parser.add_argument(
        "--encoding",
        help="""Treat given files as having a specific encoding
--encoding utf8""",
    )
    parser.add_argument("--table-name", "--table", "-t", help="Load a specific table by name")
    parser.add_argument("--table-index", type=int, help="Load a specific table by index")
    parser.add_argument("--start-row", "--skiprows", type=int, default=None, help="Skip reading x rows")
    parser.add_argument(
        "--end-row",
        "--nrows",
        "--limit",
        "-L",
        default=str(DEFAULT_FILE_ROWS_READ_LIMIT),
        help="Stop reading after x rows",
    )
    parser.add_argument(
        "--join-tables",
        "--concat",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Concat all detected tables",
    )


def table_like_post(args):
    if args.end_row.lower() in ("inf", "none", "all"):
        args.end_row = None
    else:
        args.end_row = int(args.end_row)


def filter_links(parent_parser):
    parser = parent_parser.add_argument_group("Filter Links")
    parser.add_argument(
        "--path-include",
        "--include-path",
        nargs="*",
        default=[],
        help="path substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--text-include",
        "--include-text",
        nargs="*",
        default=[],
        help="link text substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--after-include",
        "--include-after",
        nargs="*",
        default=[],
        help="plain text substrings after URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--before-include",
        "--include-before",
        nargs="*",
        default=[],
        help="plain text substrings before URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--path-exclude",
        "--exclude-path",
        nargs="*",
        default=["javascript:", "mailto:", "tel:"],
        help="path substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--text-exclude",
        "--exclude-text",
        nargs="*",
        default=[],
        help="link text substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--after-exclude",
        "--exclude-after",
        nargs="*",
        default=[],
        help="plain text substrings after URL for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--before-exclude",
        "--exclude-before",
        nargs="*",
        default=[],
        help="plain text substrings before URL for exclusion (any must match to exclude)",
    )

    parser.add_argument("--strict-include", action="store_true", help="All include args must resolve true")
    parser.add_argument("--strict-exclude", action="store_true", help="All exclude args must resolve true")
    parser.add_argument("--case-sensitive", action="store_true", help="Filter with case sensitivity")
    parser.add_argument(
        "--no-url-decode",
        "--skip-url-decode",
        action="store_true",
        help="Skip URL-decode for --path-include/--path-exclude",
    )
    parser.add_argument("--local-html", action="store_true", help="Treat paths as Local HTML files")


def filter_links_post(args):
    if not args.case_sensitive:
        args.before_include = [s.lower() for s in args.before_include]
        args.path_include = [s.lower() for s in args.path_include]
        args.text_include = [s.lower() for s in args.text_include]
        args.after_include = [s.lower() for s in args.after_include]
        args.before_exclude = [s.lower() for s in args.before_exclude]
        args.path_exclude = [s.lower() for s in args.path_exclude]
        args.text_exclude = [s.lower() for s in args.text_exclude]
        args.after_exclude = [s.lower() for s in args.after_exclude]

    if not args.no_url_decode:
        from xklb.utils.web import url_decode

        args.path_include = [url_decode(s) for s in args.path_include]
        args.path_exclude = [url_decode(s) for s in args.path_exclude]


def requests(parent_parser):
    parser = parent_parser.add_argument_group("Requests")
    parser.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]",
        help="""Load cookies from your browser
--cookies-from-browser firefox
--cookies-from-browser chrome
(uses the same syntax as yt-dlp)""",
    )
    parser.add_argument("--cookies", help="path to a Netscape formatted cookies file")
    parser.add_argument(
        "--allow-insecure",
        "--allow-untrusted",
        "--disable-tls",
        action="store_true",
        help='Allow loading data from non-TLS, non-"https" servers',
    )
    parser.add_argument("--http-max-retries", "--https-max-retries", type=int, default=8, help="Use x retries")


def selenium(parent_parser):
    parser = parent_parser.add_argument_group("Selenium")
    parser.add_argument("--selenium", "--js", action="store_true", help="Use selenium")
    parser.add_argument("--firefox", action="store_true", help="Use selenium with firefox")
    parser.add_argument("--chrome", action="store_true", help="Use selenium with chromium etc")
    parser.add_argument("--scroll", action="store_true", help="Scroll down the page; infinite scroll")
    parser.add_argument("--manual", action="store_true", help="Confirm manually in shell before exiting the browser")
    parser.add_argument(
        "--auto-pager", "--autopager", action="store_true", help="Use an auto-pager plugin to load additional pages"
    )
    parser.add_argument("--poke", action="store_true", help="Find a filled-in search box and press enter in it")


def selenium_post(args):
    if args.scroll or args.firefox or args.chrome or args.auto_pager or args.poke:
        args.selenium = True


def sample_hash_bytes(parent_parser):
    parser = parent_parser.add_argument_group("Sample Hash")
    parser.add_argument(
        "--chunk-size",
        type=int,
        help="Chunk size in bytes (default is 1%%~0.2%% dependent on file size). If set, recommended to use at least 1048576 (for performance)",
    )
    parser.add_argument(
        "--gap",
        default="0.1",
        help="Width between chunks to skip (default 10%%). Values greater than 1 are treated as number of bytes",
    )


def sample_hash_bytes_post(args):
    args.gap = nums.float_from_percent(args.gap)


def media_check(parent_parser):
    parser = parent_parser.add_argument_group("Media Check")
    parser.add_argument(
        "--chunk-size",
        type=float,
        help="Chunk size in seconds (default 0.5 second). If set, recommended to use >0.1 seconds",
        default=0.5,
    )
    parser.add_argument(
        "--gap",
        default="0.05",
        help="Width between chunks to skip (default 5%%). Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument(
        "--delete-corrupt",
        "--delete-corruption",
        help="Delete media that is more corrupt or equal to this threshold. Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument(
        "--full-scan-if-corrupt",
        "--full-scan-if-corruption",
        help="Full scan as second pass if initial scan result more corruption or equal to this threshold. Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument("--full-scan", action="store_true", help="Decode the full media file")
    parser.add_argument("--audio-scan", action="store_true", help="Count errors in audio track only")


def media_check_post(args):
    args.gap = nums.float_from_percent(args.gap)
    if args.delete_corrupt:
        args.delete_corrupt = nums.float_from_percent(args.delete_corrupt)
    if args.full_scan_if_corrupt:
        args.full_scan_if_corrupt = nums.float_from_percent(args.full_scan_if_corrupt)


def db_profiles(parser):
    profiles = parser.add_argument_group("DB Profiles")
    profiles.add_argument(
        "--audio",
        action="append_const",
        dest="profiles",
        const=DBType.audio,
        help="Extract audio metadata",
    )
    profiles.add_argument(
        "--filesystem",
        "--fs",
        action="append_const",
        dest="profiles",
        const=DBType.filesystem,
        help="Extract filesystem metadata",
    )
    profiles.add_argument(
        "--video",
        action="append_const",
        dest="profiles",
        const=DBType.video,
        help="Extract video metadata",
    )
    profiles.add_argument(
        "--text",
        action="append_const",
        dest="profiles",
        const=DBType.text,
        help="Extract text metadata",
    )
    profiles.add_argument(
        "--image",
        action="append_const",
        dest="profiles",
        const=DBType.image,
        help="Extract image metadata",
    )
    parser.add_argument("--scan-all-files", action="store_true")


def frequency(parser):
    parser.add_argument(
        "--frequency",
        "--freqency",
        "-f",
        default="monthly",
        const="monthly",
        type=str.lower,
        nargs="?",
        help=f"One of: {', '.join(consts.frequency)} (default: %(default)s)",
    )


def frequency_post(args):
    from xklb.utils.strings import partial_startswith

    args.frequency = partial_startswith(args.frequency, consts.frequency)


def history(parser):
    parser = parser.add_argument_group("History")
    history = parser.add_mutually_exclusive_group()
    history.add_argument(
        "--completed",
        "--played",
        "--watched",
        "--listened",
        action="store_true",
        help="Exclude partially watched media",
    )
    history.add_argument(
        "--in-progress",
        "--playing",
        "--watching",
        "--listening",
        action="store_true",
        help="Exclude completely watched media",
    )
