import argparse, os, sys
from typing import List, Tuple

from xklb import gdl_backend, tube_backend, usage
from xklb.media import media_printer
from xklb.utils import arg_utils, consts, db_utils, iterables, nums, objects, printing, processes, sql_utils
from xklb.utils.consts import SC, DBType
from xklb.utils.log_utils import log


def parse_args():
    parser = argparse.ArgumentParser(
        prog="library download",
        usage=usage.download,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    subp_profile = parser.add_mutually_exclusive_group()
    subp_profile.add_argument(
        "--audio",
        "--music",
        "-A",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Use audio downloader",
    )
    subp_profile.add_argument(
        "--video",
        "--movie",
        "-V",
        action="store_const",
        dest="profile",
        const=DBType.video,
        help="Use video downloader",
    )
    subp_profile.add_argument(
        "--image",
        "--photo",
        "-I",
        action="store_const",
        dest="profile",
        const=DBType.image,
        help="Use image downloader",
    )

    parser.add_argument(
        "--extractor-config",
        "-extractor-config",
        nargs=1,
        action=arg_utils.ArgparseDict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend downloader configuration",
    )
    parser.add_argument("--download-archive")
    parser.add_argument("--extra-media-data", default={}, nargs=1, action=arg_utils.ArgparseDict, metavar="KEY=VALUE")
    parser.add_argument(
        "--extra-playlist-data",
        default={},
        nargs=1,
        action=arg_utils.ArgparseDict,
        metavar="KEY=VALUE",
    )
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--same-domain", action="store_true", help="Choose a random domain to focus on")

    parser.add_argument("--subs", action="store_true")
    parser.add_argument("--auto-subs", "--autosubs", action="store_true")
    parser.add_argument("--subtitle-languages", "--subtitle-language", "--sl", action=arg_utils.ArgparseList)

    parser.add_argument("--prefix", default=os.getcwd(), help=argparse.SUPPRESS)
    parser.add_argument("--ext")

    parser.add_argument("--print", "-p", default="", const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a column when printing")
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)

    parser.add_argument("--small", action="store_true", help="Video: Prefer 480p-like")

    parser.add_argument("--photos", action="store_true", help="Image: Download JPG and WEBP")
    parser.add_argument("--drawings", action="store_true", help="Image: Download PNG")
    parser.add_argument("--gifs", action="store_true", help="Image: Download MP4 and GIFs")

    parser.add_argument(
        "--retry-delay",
        "-r",
        default="14 days",
        help="Must be specified in SQLITE Modifiers format: N hours, days, months, or years",
    )

    parser.add_argument("--force", "-f", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", "-T", help="Quit after x minutes")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database", help=argparse.SUPPRESS)
    parser.add_argument("playlists", nargs="*", action=arg_utils.ArgparseArgsOrStdin, help=argparse.SUPPRESS)
    args = parser.parse_intermixed_args()
    args.defaults = []

    if args.duration:
        args.duration = sql_utils.parse_human_to_sql(nums.human_to_seconds, "duration", args.duration)

    if not args.profile and not args.print:
        log.error("Download profile must be specified. Use one of: --video OR --audio OR --image")
        raise SystemExit(1)

    args.playlists = iterables.conform(args.playlists)

    if args.db:
        args.database = args.db
    args.db = db_utils.connect(args)

    args.action = SC.download
    arg_utils.parse_args_sort(args)
    arg_utils.parse_args_limit(args)

    processes.timeout(args.timeout)

    log.info(objects.dict_filter_bool(args.__dict__))

    return args


def construct_query(args) -> Tuple[str, dict]:
    m_columns = db_utils.columns(args, "media")
    pl_columns = db_utils.columns(args, "playlists")

    args.filter_sql = []
    args.filter_bindings = {}

    if args.duration:
        args.filter_sql.append(" and duration IS NOT NULL " + args.duration)

    args.filter_sql.extend([" and " + w for w in args.where])

    db_utils.construct_search_bindings(
        args,
        [f"m.{k}" for k in m_columns if k in db_utils.config["media"]["search_columns"]],
    )

    if args.action == SC.download and "time_modified" in m_columns:
        args.filter_sql.append(
            f"""and cast(STRFTIME('%s',
            datetime( COALESCE(m.time_modified,0), 'unixepoch', '+{args.retry_delay}')
            ) as int) < STRFTIME('%s', datetime()) """,
        )

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    same_subdomain = """AND m.path like (
        SELECT '%' || SUBSTR(path, INSTR(path, '//') + 2, INSTR( SUBSTR(path, INSTR(path, '//') + 2), '/') - 1) || '%'
        FROM media
        WHERE 1=1
            AND COALESCE(time_downloaded,0) = 0
            AND COALESCE(time_deleted,0) = 0
        ORDER BY RANDOM()
        LIMIT 1
    )"""
    if "playlist_id" in m_columns:
        query = f"""select
                m.id
                , m.path
                , p.path playlist_path
                {', m.title' if 'title' in m_columns else ''}
                {', m.duration' if 'duration' in m_columns else ''}
                , m.time_created
                {', m.size' if 'size' in m_columns else ''}
                {', m.time_modified' if 'time_modified' in m_columns else ''}
                {', m.time_downloaded' if 'time_downloaded' in m_columns else ''}
                {', m.time_deleted' if 'time_deleted' in m_columns else ''}
                {', m.error' if 'error' in m_columns and args.verbose >= consts.LOG_DEBUG else ''}
                {', p.extractor_config' if 'extractor_config' in pl_columns else ''}
                , p.extractor_key
            FROM media m
            LEFT JOIN playlists p on p.id = m.playlist_id
            WHERE 1=1
                and COALESCE(m.time_downloaded,0) = 0
                and COALESCE(m.time_deleted,0) = 0
                {'and COALESCE(p.time_deleted, 0) = 0' if 'time_deleted' in pl_columns else ''}
                and m.path like "http%"
                {same_subdomain if getattr(args, 'same_domain', False) else ''}
                {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
                {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
                {" ".join(args.filter_sql)}
            ORDER BY 1=1
                , COALESCE(m.time_modified, 0) = 0 DESC
                {', p.extractor_key IS NOT NULL DESC' if 'sort' in args.defaults else ''}
                {', m.error IS NULL DESC' if 'error' in m_columns else ''}
                {', random()' if 'sort' in args.defaults else ', ' + args.sort}
            {LIMIT}
        """
    else:
        query = f"""select
                m.path
                {', m.title' if 'title' in m_columns else ''}
                {', m.duration' if 'duration' in m_columns else ''}
                {', m.time_created' if 'time_created' in m_columns else ''}
                {', m.size' if 'size' in m_columns else ''}
                {', m.time_modified' if 'time_modified' in m_columns else ''}
                {', m.time_downloaded' if 'time_downloaded' in m_columns else ''}
                {', m.time_deleted' if 'time_deleted' in m_columns else ''}
                {', m.error' if 'error' in m_columns and args.verbose >= consts.LOG_DEBUG else ''}
                , 'Playlist-less media' as extractor_key
            FROM media m
            WHERE 1=1
                {'and COALESCE(m.time_downloaded,0) = 0' if 'time_downloaded' in m_columns else ''}
                {'and COALESCE(m.time_deleted,0) = 0' if 'time_deleted' in m_columns else ''}
                and m.path like "http%"
                {same_subdomain if args.same_domain else ''}
                {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
                {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
                {" ".join(args.filter_sql)}
            ORDER BY 1=1
                , COALESCE(m.time_modified, 0) = 0 DESC
                {', m.error IS NULL DESC' if 'error' in m_columns else ''}
                {', random()' if 'sort' in args.defaults else ', ' + args.sort}
        {LIMIT}
        """

    return query, args.filter_bindings


def process_downloadqueue(args) -> List[dict]:
    query, bindings = construct_query(args)
    if args.print:
        media_printer.printer(args, query, bindings)
        return []

    media = list(args.db.query(query, bindings))
    if not media:
        processes.no_media_found()
    return media


def mark_download_attempt(args, paths) -> int:
    paths = iterables.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = iterables.chunks(paths, consts.SQLITE_PARAM_LIMIT)
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


def dl_download(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args()
    m_columns = db_utils.columns(args, "media")

    if "limit" in args.defaults and "media" in args.db.table_names() and "webpath" in m_columns:
        if args.db.pop("SELECT 1 from media WHERE webpath is NULL and path in (select webpath from media) LIMIT 1"):
            with args.db.conn:
                args.db.conn.execute("DELETE from media WHERE webpath is NULL and path in (select webpath from media)")

    args.blocklist_rules = []
    if "blocklist" in args.db.table_names():
        args.blocklist_rules = [{d["key"]: d["value"]} for d in args.db["blocklist"].rows]

    media = process_downloadqueue(args)
    for m in media:
        if args.blocklist_rules and sql_utils.is_blocked_dict_like_sql(m, args.blocklist_rules):
            mark_download_attempt(args, [m["path"]])
            continue

        if args.safe:
            if (args.profile in (DBType.audio, DBType.video) and not tube_backend.is_supported(m["path"])) or (
                args.profile in (DBType.image) and not gdl_backend.is_supported(args, m["path"])
            ):
                log.info("[%s]: Skipping unsupported URL (safe_mode)", m["path"])
                mark_download_attempt(args, [m["path"]])
                continue

        # check if download already attempted recently by another process
        previous_time_attempted = m.get("time_modified") or consts.APPLICATION_START  # 0 is nullified
        if not args.force and "time_modified" in m_columns:
            d = args.db.pop_dict(
                f"""
                SELECT time_modified, time_deleted from media m
                WHERE 1=1
                AND path=?
                AND (time_modified > {str(previous_time_attempted)} OR time_deleted > 0)
                """,
                [m["path"]],
            )
            log.debug(d)
            if d:
                if d["time_deleted"]:
                    log.info(
                        "[%s]: Download marked deleted (%s ago). Skipping!",
                        m["path"],
                        printing.human_duration(consts.now() - d["time_deleted"]),
                    )
                    mark_download_attempt(args, [m["path"]])
                    continue
                elif d["time_modified"]:
                    log.info(
                        "[%s]: Download already attempted recently (%s ago). Skipping!",
                        m["path"],
                        printing.human_duration(consts.now() - d["time_modified"]),
                    )
                    continue

        try:
            log.debug(m)

            if args.profile in (DBType.audio, DBType.video):
                tube_backend.download(args, m)
            elif args.profile == DBType.image:
                gdl_backend.download(args, m)
            else:
                raise NotImplementedError
        except Exception:
            print("db:", args.database)
            raise
