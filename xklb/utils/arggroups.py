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


def args_post(args, parser, create_db=False):
    args.defaults = [k for k, v in args.__dict__.items() if parser.get_default(k) == v]
    settings = {k: v for k, v in args.__dict__.items() if k not in ["database", "verbose", "defaults"] + args.defaults}
    args.extractor_config = {
        k: v for k, v in settings.items() if k not in ["db", "paths", "actions", "backfill_pages"]
    } | (getattr(args, "extractor_config", None) or {})

    log_args = objects.dict_filter_bool(settings)
    if log_args:
        log.info({k: textwrap.shorten(str(v), 140) for k, v in log_args.items()})

    if create_db:
        Path(args.database).touch()
        args.db = db_utils.connect(args)
    elif getattr(args, "database", False):
        args.db = db_utils.connect(args)

    if getattr(args, "timeout", False):
        processes.timeout(args.timeout)


def printing(parser):
    printing = parser.add_argument_group("Printing")
    printing.add_argument("--print", "-p", default="", const="p", nargs="?")
    printing.add_argument("--to-json", action="store_true", help="Write JSONL to stdout")
    printing.add_argument("--cols", "--columns", nargs="*", help="Include specific column(s) when printing")


def debug(parent_parser):
    parser = parent_parser.add_argument_group("Global options")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--timeout", "-T", help="Quit after x minutes")
    parser.add_argument("--ext", "-e", default=[], action=argparse_utils.ArgparseList, help="Filter by file extension")
    printing(parent_parser)


def capability_soft_delete(parent_parser):
    parser = parent_parser.add_argument_group("Modify Metadata")
    parser.add_argument("--mark-deleted", "--soft-delete", action="store_true", help="Mark matching rows as deleted")
    parser.add_argument("--mark-watched", action="store_true", help="Mark matching rows as watched")
    parser.add_argument("--delete-rows", action="store_true", help="Delete matching rows")


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
        help="Delete files from filesystem",
    )


def database(parent_parser):
    parser = parent_parser.add_argument_group("Database")
    capability_soft_delete(parent_parser)
    capability_delete(parent_parser)
    parser.add_argument("--db", "-db", help="Positional argument override")
    parser.add_argument("database")


def paths_or_stdin(parent_parser):
    parser = parent_parser.add_argument_group("Paths")
    parser.add_argument(
        "--from-file",
        "--from-text",
        "--file",
        action="store_true",
        help="Read paths from line-delimited file(s)",
    )
    parser.add_argument("--from-json", "--json", action="store_true", help="Read JSON or JSONL from stdin")
    parser.add_argument(
        "paths", nargs="*", default=argparse_utils.STDIN_DASH, action=argparse_utils.ArgparseArgsOrStdin
    )


def sql_fs(parent_parser):
    parse_fs = parent_parser.add_argument_group("FileSystemDB SQL")
    parse_fs.add_argument("--limit", "--queue", "-n", "-L", "-l")
    parse_fs.add_argument("--offset")
    parse_fs.add_argument("--sort", "-u", nargs="+", default=[])
    parse_fs.add_argument("--random", "-r", action="store_true")

    parse_fs.add_argument("--playlists", nargs="+", action="extend", default=[])

    parse_fs.add_argument("--where", "-w", nargs="+", action="extend", default=[])
    parse_fs.add_argument("--include", "--search", "-s", nargs="+", action="extend", default=[])
    parse_fs.add_argument("--exclude", "-E", nargs="+", action="extend", default=[])
    parse_fs.add_argument("--exact", action="store_true")
    parse_fs.add_argument("--flexible-search", "--or", "--flex", action="store_true")
    parse_fs.add_argument("--fts", action=argparse.BooleanOptionalAction, default=True)

    parse_fs.add_argument("--online-media-only", "--online", action="store_true")
    parse_fs.add_argument("--local-media-only", "--local", action="store_true")

    parse_fs.add_argument(
        "--sizes",
        "-S",
        action="append",
        help="Only include files of specific sizes (uses the same syntax as fd-find)",
    )

    parse_fs.add_argument("--created-within")
    parse_fs.add_argument("--created-before")
    parse_fs.add_argument("--changed-within", "--modified-within")
    parse_fs.add_argument("--changed-before", "--modified-before")
    parse_fs.add_argument("--deleted-within")
    parse_fs.add_argument("--deleted-before")
    parse_fs.add_argument("--downloaded-within")
    parse_fs.add_argument("--downloaded-before")

    parse_media = parent_parser.add_argument_group("MediaDB SQL")
    parse_media.add_argument("--no-video", "-vn", action="store_true")
    parse_media.add_argument("--no-audio", "-an", action="store_true")
    parse_media.add_argument(
        "--no-subtitles",
        "--no-subtitle",
        "--no-subs",
        "--nosubs",
        "-sn",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parse_media.add_argument("--subtitles", "--subtitle", "-sy", action="store_true")

    parse_media.add_argument("--played-within")
    parse_media.add_argument("--played-before")

    parse_media.add_argument("--duration", "-d", action="append")
    parse_media.add_argument("--duration-from-size", action="append")

    parse_media.add_argument("--portrait", action="store_true")


def sql_fs_post(args) -> None:
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
        args.filter_sql.append("AND COALESCE(m.time_deleted,0) = 0")

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
            f"and time_last_played >= cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.played_within)}')) as int)",
        )
    if args.played_before:
        args.aggregate_filter_sql.append(
            f"and time_last_played < cast(STRFTIME('%s', datetime( 'now', '-{nums.sql_human_time(args.played_before)}')) as int)",
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
    parser.add_argument("--crop", "--zoom", "--stretch", "--fit", "--fill", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--start", "-vs")
    parser.add_argument("--end", "-ve")
    parser.add_argument("--volume", type=float)

    parser.add_argument("--mpv-socket")
    parser.add_argument("--auto-seek", action="store_true")

    parser.add_argument("--override-player", "--player")
    parser.add_argument(
        "--ignore-errors",
        "--ignoreerrors",
        "-i",
        action="store_true",
        help="After a playback error continue to the next track instead of exiting",
    )

    parser.add_argument("--prefetch", type=int, default=3)
    parser.add_argument("--prefix", default="", help=argparse.SUPPRESS)

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
    parser.add_argument("--exit-code-confirm", action="store_true")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--keep-dir", "--keepdir")
    parser.add_argument("--post-action", "--action", "-k", default="keep")


def post_actions_post(args):
    if args.keep_dir:
        args.keep_dir = Path(args.keep_dir).expanduser().resolve()

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
    )
    parser.add_argument("--screen-name")
    parser.add_argument("--hstack", action="store_true")
    parser.add_argument("--vstack", action="store_true")


def multiple_playback_post(args):
    if args.multiple_playback > 1:
        args.gui = True


def extractor(parent_parser):
    parser = parent_parser.add_argument_group("Extractor")
    parser.add_argument("--no-sanitize", action="store_true", help="Don't sanitize some common URL parameters")
    parser.add_argument(
        "--insert-only", "--no-extract", "--skip-extract", action="store_true"
    )  # TODO: move to its own subcommand
    parser.add_argument(
        "--insert-only-playlists",
        "--insert-only-playlist",
        "--no-extract-playlists",
        "--skip-extract-playlists",
        action="store_true",
    )
    parser.add_argument("--extra", action="store_true", help="Get full metadata (takes a lot longer)")
    parser.add_argument("--threads", type=int, default=4)


def extractor_post(args):
    from xklb.utils.path_utils import sanitize_url

    if hasattr(args, "paths"):
        args.paths = list({s.strip() for s in args.paths})
        if not args.no_sanitize:
            args.paths = [sanitize_url(args, p) for p in args.paths]
        args.paths = iterables.conform(args.paths)


def group_folders(parent_parser):
    parser = parent_parser.add_argument_group("Group Folders")
    parser.add_argument("--big-dirs", "--bigdirs", "-B", action="count", default=0)

    parser.add_argument(
        "--sibling", "--episode", "--episodic", action="store_true", help="Shorthand for --folder-counts '>1'"
    )
    parser.add_argument("--solo", action="store_true", help="Shorthand for --folder-counts=1")

    parser.add_argument("--sort-groups-by", "--sort-groups", "--sort-by", nargs="+")
    parser.add_argument("--depth", "-D", type=int, help="Depth of folders")
    parser.add_argument("--parents", action="store_true")

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
        help="Number of files per folder",
    )
    parser.add_argument("--folders-count", action="append", help="TODO: Number of folders per folder")


def group_folders_post(args) -> None:
    if args.solo:
        args.folder_counts = ["1"]
    if args.sibling:
        args.folder_counts = ["+2"]

    if args.folder_sizes:
        args.folder_sizes = sql_utils.parse_human_to_lambda(nums.human_to_bytes, args.folder_sizes)
    if args.folder_counts:
        args.folder_counts = sql_utils.parse_human_to_lambda(int, args.folder_counts)

    if args.sort_groups_by:
        args.sort_groups_by = arg_utils.parse_ambiguous_sort(args.sort_groups_by)
        args.sort_groups_by = ",".join(args.sort_groups_by)


def cluster(parent_parser):
    parser = parent_parser.add_argument_group("Cluster")
    parser.add_argument("--cluster-sort", "--cluster", "-C", action="store_true", help="Cluster by filename TF-IDF")
    parser.add_argument("--clusters", "--n-clusters", type=int, help="Number of KMeans clusters")
    parser.add_argument("--stop-words", "--ignore-words", nargs="+", action="append")

    parser.add_argument("--print-groups", "--groups", "-g", action="store_true", help="Print groups")
    parser.add_argument("--move-groups", "-M", action="store_true", help="Move groups into subfolders")

    parser.add_argument("--near-duplicates", "--similar-only", action="store_true", help="Re-group by difflib ratio")
    parser.add_argument(
        "--unique-only", action="store_true", help="Include only 'unique' lines (not including originals or duplicates)"
    )
    parser.add_argument("--exclude-unique", "--no-unique", action="store_true", help="Exclude 'unique' lines")


def related(parser):
    parser.add_argument("--related", "-R", action="count", default=0)


def clobber(parent_parser):
    parser = parent_parser.add_argument_group("Replace Files")
    parser.add_argument(
        "--replace", "--clobber", action=argparse.BooleanOptionalAction, help="Overwrite files on path conflict"
    )


def simulate(parser):
    parser.add_argument("--simulate", "--dry-run", action="store_true")


def process_ffmpeg(parent_parser):
    parser = parent_parser.add_argument_group("FFMPEG Processing")
    parser.add_argument("--delete-unplayable", action="store_true")

    parser.add_argument("--delete-no-video", action="store_true")
    parser.add_argument("--delete-no-audio", action="store_true")

    parser.add_argument("--max-height", type=int, default=960)
    parser.add_argument("--max-width", type=int, default=1440)
    parser.add_argument("--max-width-buffer", type=float, default=0.2)
    parser.add_argument("--max-height-buffer", type=float, default=0.2)

    parser.add_argument("--always-split", "--force-split", action="store_true")
    parser.add_argument("--split-longer-than")
    parser.add_argument("--min-split-segment", default=consts.DEFAULT_MIN_SPLIT)

    parser.add_argument("--audio-only", action="store_true", help="Only extract audio")
    parser.add_argument("--no-preserve-video", action="store_true")

    parser.add_argument("--max-image-height", type=int, default=2400)
    parser.add_argument("--max-image-width", type=int, default=2400)


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
    parser.add_argument("--download-archive")
    parser.add_argument("--extract-audio-ext", default="opus")

    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true")
    parser.add_argument("--safe", action="store_true", help="Skip generic URLs")

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
    parser.add_argument("--subs", action="store_true")
    parser.add_argument("--auto-subs", "--autosubs", action="store_true")
    parser.add_argument("--subtitle-languages", "--subtitle-language", "--sl", action=argparse_utils.ArgparseList)


def table_like(parent_parser):
    parser = parent_parser.add_argument_group("Table-like")
    parser.add_argument("--mimetype", "--filetype")
    parser.add_argument("--encoding")
    parser.add_argument("--table-name", "--table", "-t")
    parser.add_argument("--table-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--end-row", "--nrows", "--limit", "-L", default=str(DEFAULT_FILE_ROWS_READ_LIMIT))


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
    parser.add_argument("--cookies", help="path to a Netscape formatted cookies file")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]")
    parser.add_argument("--allow-insecure", "--allow-untrusted", "--disable-tls", action="store_true")
    parser.add_argument("--http-max-retries", "--https-max-retries", type=int)


def selenium(parent_parser):
    parser = parent_parser.add_argument_group("Selenium")
    parser.add_argument("--selenium", "--js", action="store_true")
    parser.add_argument("--firefox", action="store_true")
    parser.add_argument("--chrome", action="store_true")
    parser.add_argument("--scroll", action="store_true", help="Scroll down the page; infinite scroll")
    parser.add_argument("--manual", action="store_true", help="Confirm manually in shell before exiting the browser")
    parser.add_argument("--auto-pager", "--autopager", action="store_true")
    parser.add_argument("--poke", action="store_true")


def selenium_post(args):
    if args.scroll or args.firefox or args.chrome or args.auto_pager or args.poke:
        args.selenium = True


def sample_hash_bytes(parent_parser):
    parser = parent_parser.add_argument_group("Sample Hash")
    parser.add_argument("--threads", default=1, const=10, nargs="?")
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
    parser.add_argument("--threads", default=1, const=10, nargs="?")
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
    parser.add_argument("--full-scan", action="store_true")
    parser.add_argument("--audio-scan", action="store_true")


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
    history.add_argument("--completed", "--played", "--watched", "--listened", action="store_true")
    history.add_argument("--in-progress", "--playing", "--watching", "--listening", action="store_true")
