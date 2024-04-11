import argparse

from xklb.utils import argparse_utils, consts
from xklb.utils.consts import DEFAULT_FILE_ROWS_READ_LIMIT, DBType


def debug(parser):
    parser.add_argument("--verbose", "-v", action="count", default=0)


def database(parser):
    parser.add_argument("--db", "-db", dest="database", help="Positional argument override")
    parser.add_argument("database")


def paths_or_stdin(parser):
    parser.add_argument("--file", "-f", help="File with one URL per line")
    parser.add_argument(
        "paths", nargs="*", default=argparse_utils.STDIN_DASH, action=argparse_utils.ArgparseArgsOrStdin
    )


def sql_fs(parser):
    parser.add_argument("--print", "-p", default="", const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "--col", nargs="*", help="Include specific column(s) when printing")

    parser.add_argument("--limit", "--queue", "--count", "-n", "-L", "-l", help=argparse.SUPPRESS)
    parser.add_argument("--offset", help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--random", "-r", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "--search", "-s", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--flexible-search", "--or", "--flex", action="store_true")
    parser.add_argument("--no-fts", action="store_true")

    parser.add_argument("--ext", "-e", default=[], action=argparse_utils.ArgparseList)

    parser.add_argument(
        "--size",
        "-S",
        action="append",
        help="Only include files of specific sizes (uses the same syntax as fd-find)",
    )

    parser.add_argument("--created-within", help=argparse.SUPPRESS)
    parser.add_argument("--created-before", help=argparse.SUPPRESS)
    parser.add_argument("--changed-within", "--modified-within", help=argparse.SUPPRESS)
    parser.add_argument("--changed-before", "--modified-before", help=argparse.SUPPRESS)
    parser.add_argument("--deleted-within", help=argparse.SUPPRESS)
    parser.add_argument("--deleted-before", help=argparse.SUPPRESS)
    parser.add_argument("--downloaded-within", help=argparse.SUPPRESS)
    parser.add_argument("--downloaded-before", help=argparse.SUPPRESS)
    parser.add_argument("--played-within", help=argparse.SUPPRESS)
    parser.add_argument("--played-before", help=argparse.SUPPRESS)


def sql_media(parser):
    parser.add_argument("--online-media-only", "--online", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--local-media-only", "--local", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--no-video", "-vn", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-audio", "-an", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-subtitles",
        "--no-subtitle",
        "--no-subs",
        "--nosubs",
        "-sn",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--subtitles", "--subtitle", "-sy", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--duration-from-size", action="append", help=argparse.SUPPRESS)

    parser.add_argument("--portrait", "-portrait", action="store_true", help=argparse.SUPPRESS)


def playback(parser):
    parser.add_argument("--crop", "--zoom", "--stretch", "--fit", "--fill", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--loop", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--start", "-vs", help=argparse.SUPPRESS)
    parser.add_argument("--end", "-ve", help=argparse.SUPPRESS)
    parser.add_argument("--volume", type=float)

    parser.add_argument("--mpv-socket", help=argparse.SUPPRESS)
    parser.add_argument("--auto-seek", action="store_true")

    parser.add_argument("--override-player", "--player", help=argparse.SUPPRESS)
    parser.add_argument(
        "--ignore-errors",
        "--ignoreerrors",
        "-i",
        action="store_true",
        help="After a playback error continue to the next track instead of exiting",
    )

    parser.add_argument("--folder", action="store_true", help="Experimental escape hatch to open folder")
    parser.add_argument(
        "--folder-glob",
        "--folderglob",
        type=int,
        default=False,
        const=10,
        nargs="?",
        help="Experimental escape hatch to open a folder glob limited to x number of files",
    )


def post_actions(parser):
    parser.add_argument("--exit-code-confirm", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--keep-dir", "--keepdir", help=argparse.SUPPRESS)
    parser.add_argument("--post-action", "--action", "-k", default="keep", help=argparse.SUPPRESS)


def multiple_playback(parser):
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
    parser.add_argument("--hstack", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--vstack", action="store_true", help=argparse.SUPPRESS)


def extractor(parser):
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


def operation_group_folders(parser):
    parser.add_argument("--lower", type=int, help="Minimum number of files per folder")
    parser.add_argument("--upper", type=int, help="Maximum number of files per folder")

    parser.add_argument("--sort-groups-by", "--sort-groups", "--sort-by", nargs="+")
    parser.add_argument("--depth", "-D", type=int, help="Depth of folders")

    parser.add_argument(
        "--folder-size",
        "--foldersize",
        "-Z",
        action="append",
        help="Only include folders of specific sizes (uses the same syntax as fd-find)",
    )


def operation_cluster(parser):
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


def operation_related(parser):
    parser.add_argument("--related", "-R", action="count", default=0, help=argparse.SUPPRESS)


def capability_delete(parser):
    parser.add_argument("--mark-deleted", "--soft-delete", action="store_true", help="Mark matching rows as deleted")
    parser.add_argument(
        "--delete",
        "--remove",
        "--rm",
        action="store_true",
        help="Delete matching rows",
    )


def capability_clobber(parser):
    parser.add_argument("--replace", "--clobber", action="store_true")
    parser.add_argument("--no-replace", "--no-clobber", action="store_true")


def capability_simulate(parser):
    parser.add_argument("--simulate", "--dry-run", action="store_true")


def process_ffmpeg(parser):
    parser.add_argument("--delete-no-video", action="store_true")
    parser.add_argument("--delete-no-audio", action="store_true")

    parser.add_argument("--max-height", type=int, default=960)
    parser.add_argument("--max-width", type=int, default=1440)
    parser.add_argument("--max-width-buffer", type=float, default=0.2)
    parser.add_argument("--max-height-buffer", type=float, default=0.2)

    parser.add_argument("--always-split", "--force-split", action="store_true")
    parser.add_argument("--split-longer-than")
    parser.add_argument("--min-split-segment", default=consts.DEFAULT_MIN_SPLIT)

    parser.add_argument("--audio-only", "-vn", action="store_true", help="Only extract audio")
    parser.add_argument("--no-preserve-video", action="store_true")


def download(parser):
    parser.add_argument(
        "--extractor-config",
        "-extractor-config",
        nargs=1,
        action=argparse_utils.ArgparseDict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default extractor/downloader configuration",
    )
    parser.add_argument("--download-archive")

    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true")
    parser.add_argument("--safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--timeout", "-T", help="Quit after x minutes")

    parser.add_argument(
        "--retry-delay",
        default="14 days",
        help="Must be specified in SQLITE Modifiers format: N seconds, minutes, hours, days, months, or years",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Fetch metadata for paths even if they are already in the media table",
    )


def download_subtitle(parser):
    parser.add_argument("--subs", action="store_true")
    parser.add_argument("--auto-subs", "--autosubs", action="store_true")
    parser.add_argument("--subtitle-languages", "--subtitle-language", "--sl", action=argparse_utils.ArgparseList)


def table_like(parser):
    parser.add_argument("--mimetype", "--filetype")
    parser.add_argument("--encoding")
    parser.add_argument("--table-name", "--table", "-t")
    parser.add_argument("--table-index", type=int)
    parser.add_argument("--start-row", "--skiprows", type=int, default=None)
    parser.add_argument("--end-row", "--nrows", "--limit", "-L", default=str(DEFAULT_FILE_ROWS_READ_LIMIT))


def filter_links(parser):
    parser.add_argument(
        "--path-include",
        "--include-path",
        "--include",
        "-s",
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
        "--exclude",
        "-E",
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


def requests(parser):
    parser.add_argument("--cookies", help="path to a Netscape formatted cookies file")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]")
    parser.add_argument("--allow-insecure", "--allow-untrusted", "--disable-tls", action="store_true")


def selenium(parser):
    parser.add_argument("--selenium", "--js", "--firefox", action="store_true")
    parser.add_argument("--chrome", action="store_true")
    parser.add_argument("--scroll", action="store_true", help="Scroll down the page; infinite scroll")
    parser.add_argument("--manual", action="store_true", help="Confirm manually in shell before exiting the browser")
    parser.add_argument("--auto-pager", "--autopager", action="store_true")
    parser.add_argument("--poke", action="store_true")


def sample_hash_bytes(parser):
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


def media_check(parser):
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


def db_profiles(parser):
    profiles = parser.add_argument_group()
    profiles.add_argument(
        "--audio",
        "-A",
        action="append_const",
        dest="profiles",
        const=DBType.audio,
        help="Extract audio metadata",
    )
    profiles.add_argument(
        "--filesystem",
        "--fs",
        "-F",
        action="append_const",
        dest="profiles",
        const=DBType.filesystem,
        help="Extract filesystem metadata",
    )
    profiles.add_argument(
        "--video",
        "-V",
        action="append_const",
        dest="profiles",
        const=DBType.video,
        help="Extract video metadata",
    )
    profiles.add_argument(
        "--text",
        "-T",
        action="append_const",
        dest="profiles",
        const=DBType.text,
        help="Extract text metadata",
    )
    profiles.add_argument(
        "--image",
        "-I",
        action="append_const",
        dest="profiles",
        const=DBType.image,
        help="Extract image metadata",
    )
    parser.add_argument("--scan-all-files", "-a", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ext", "-e", default=[], action=argparse_utils.ArgparseList)


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
