import argparse, os, sys
from typing import List, Tuple

from xklb import consts, db, play_actions, player, tube_backend, utils
from xklb.consts import SC, DBType
from xklb.utils import log


def parse_args(action, usage):
    parser = argparse.ArgumentParser(
        prog="library " + action,
        usage=usage,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    subp_profile = parser.add_mutually_exclusive_group()
    subp_profile.add_argument(
        "--audio",
        "-A",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Use audio downloader",
    )
    subp_profile.add_argument(
        "--video",
        "-V",
        action="store_const",
        dest="profile",
        const=DBType.video,
        help="Use video downloader",
    )
    subp_profile.add_argument(
        "--image",
        "-I",
        action="store_const",
        dest="profile",
        const=DBType.image,
        help="Use image downloader",
    )

    parser.add_argument(
        "--dl-config",
        "-dl-config",
        nargs=1,
        action=utils.ArgparseDict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend downloader configuration",
    )
    parser.add_argument("--download-archive", default="~/.local/share/yt_archive.txt")
    parser.add_argument("--extra-media-data", default={}, nargs=1, action=utils.ArgparseDict, metavar="KEY=VALUE")
    parser.add_argument("--extra-playlist-data", default={}, nargs=1, action=utils.ArgparseDict, metavar="KEY=VALUE")
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")

    parser.add_argument("--prefix", default=os.getcwd(), help=argparse.SUPPRESS)
    parser.add_argument("--ext", default="DEFAULT")
    parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", default=["random"], help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--small", action="store_true", help="Prefer 480p-like")
    parser.add_argument(
        "--retry-delay",
        "-r",
        default="14 days",
        help="Must be specified in SQLITE Modifiers format: N hours, days, months, or years",
    )

    if action == SC.block:
        parser.add_argument("--all-deleted-playlists", "--all", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database", help=argparse.SUPPRESS)
    parser.add_argument("playlists", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_intermixed_args()

    if action == SC.download:
        if args.duration:
            args.duration = utils.parse_human_to_sql(utils.human_to_seconds, "duration", args.duration)

        if not args.profile and not args.print:
            log.error("Download profile must be specified. Use one of: --video --audio")
            raise SystemExit(1)

    if args.db:
        args.database = args.db
    args.db = db.connect(args)

    args.playlists = utils.conform(args.playlists)

    args.action = action
    play_actions.parse_args_sort(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def construct_query(args) -> Tuple[str, dict]:
    utils.ensure_playlists_exists(args)

    m_columns = args.db["media"].columns_dict
    pl_columns = args.db["playlists"].columns_dict

    args.filter_sql = []
    args.filter_bindings = {}

    if args.duration:
        args.filter_sql.append(" and duration IS NOT NULL " + args.duration)

    args.filter_sql.extend([" and " + w for w in args.where])

    play_actions.construct_search_bindings(args, m_columns)

    args.filter_sql.append(
        f"""and cast(STRFTIME('%s',
          datetime( COALESCE(time_modified,0), 'unixepoch', '+{args.retry_delay}')
        ) as int) < STRFTIME('%s', datetime()) """,
    )

    if "uploader" in m_columns:
        args.filter_sql.append(
            f"and (m.uploader is NULL or m.uploader not in (select uploader from playlists where category='{consts.BLOCK_THE_CHANNEL}'))",
        )

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    if "playlist_path" in m_columns:
        query = f"""select
                m.path
                , playlist_path
                , m.title
                {', m.duration' if 'duration' in m_columns else ''}
                , m.time_created
                {', m.size' if 'size' in m_columns else ''}
                {', m.ie_key' if 'ie_key' in m_columns else ''}
                {', m.time_modified' if 'time_modified' in m_columns else ''}
                {', m.time_downloaded' if 'time_downloaded' in m_columns else ''}
                {', m.time_deleted' if 'time_deleted' in m_columns else ''}
                {', m.error' if 'error' in m_columns else ''}
                {', m.id' if 'id' in m_columns else ''}
                {', p.dl_config' if 'dl_config' in pl_columns else ''}
                , coalesce(p.category, p.ie_key) category
            FROM media m
            LEFT JOIN playlists p on (p.path = m.playlist_path {"and p.ie_key != 'Local' and p.ie_key = m.ie_key" if 'ie_key' in m_columns else ''})
            WHERE 1=1
                and COALESCE(m.time_downloaded,0) = 0
                and COALESCE(m.time_deleted,0) = 0
                and COALESCE(p.time_deleted,0) = 0
                and m.path like "http%"
                {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
                {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
                {" ".join(args.filter_sql)}
            ORDER BY 1=1
                , play_count
                {', ' + args.sort if args.sort else ''}
                , random()
        {LIMIT}
        """
    else:
        query = f"""select
                m.path
                , m.title
                {', m.duration' if 'duration' in m_columns else ''}
                , m.time_created
                {', m.size' if 'size' in m_columns else ''}
                {', m.ie_key' if 'ie_key' in m_columns else ''}
                {', m.time_modified' if 'time_modified' in m_columns else ''}
                {', m.time_downloaded' if 'time_downloaded' in m_columns else ''}
                {', m.time_deleted' if 'time_deleted' in m_columns else ''}
                {', m.error' if 'error' in m_columns else ''}
                {', m.id' if 'id' in m_columns else ''}
            FROM media m
            WHERE 1=1
                and COALESCE(m.time_downloaded,0) = 0
                and COALESCE(m.time_deleted,0) = 0
                and m.path like "http%"
                {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
                {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
                {" ".join(args.filter_sql)}
            ORDER BY 1=1
                , play_count
                {', ' + args.sort if args.sort else ''}
                , random()
        {LIMIT}
        """

    return query, args.filter_bindings


def process_downloadqueue(args) -> List[dict]:
    query, bindings = construct_query(args)

    if args.print:
        player.printer(args, query, bindings)
        return []

    media = list(args.db.query(query, bindings))
    if not media:
        utils.no_media_found()

    return media


def dl_download(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(
        SC.download,
        usage=r"""library download database [--prefix /mnt/d/] --video | --audio

    Download stuff in a random order.

        library download dl.db --prefix ~/output/path/root/

    Download stuff in a random order, limited to the specified playlist URLs.

        library download dl.db https://www.youtube.com/c/BlenderFoundation/videos

    Files will be saved to <lb download prefix>/<lb download category>/

        For example:
        library dladd Cool ...
        library download D:\'My Documents'\ ...
        Media will be downloaded to 'D:\My Documents\Cool\'

    Print list of queued up downloads

        library download --print

    Print list of saved playlists

        library playlists dl.db -p a

    Print download queue groups

        library dlstatus audio.db
        ╒═════════════════════╤════════════╤══════════════════╤════════════════════╤══════════╕
        │ category            │ ie_key     │ duration         │   never_downloaded │   errors │
        ╞═════════════════════╪════════════╪══════════════════╪════════════════════╪══════════╡
        │ 81_New_Music        │ Soundcloud │                  │                 10 │        0 │
        ├─────────────────────┼────────────┼──────────────────┼────────────────────┼──────────┤
        │ 81_New_Music        │ Youtube    │ 10 days, 4 hours │                  1 │     2555 │
        │                     │            │ and 20 minutes   │                    │          │
        ├─────────────────────┼────────────┼──────────────────┼────────────────────┼──────────┤
        │ Playlist-less media │ Youtube    │ 7.68 minutes     │                 99 │        1 │
        ╘═════════════════════╧════════════╧══════════════════╧════════════════════╧══════════╛
    """,
    )
    m_columns = args.db["media"].columns_dict

    if "media" in args.db.table_names() and "webpath" in m_columns:
        with args.db.conn:
            args.db.conn.execute("DELETE from media WHERE webpath is NULL and path in (select webpath from media)")

    media = process_downloadqueue(args)
    for m in media:
        if args.safe and not tube_backend.is_supported(m["path"]):
            log.info("[%s]: Skipping unsupported URL (safe_mode)", m["path"])
            continue

        # check again in case it was already attempted by another process
        previous_time_attempted = m.get("time_modified") or 0
        download_already_attempted = list(
            args.db.query(
                f"""
                SELECT path from media
                WHERE 1=1
                AND (path=? or {'web' if 'webpath' in m_columns else ''}path=?)
                {f'AND COALESCE(time_modified,0) > {str(previous_time_attempted)}' if 'time_modified' in m_columns else ''}
                """,
                [m["path"], m["path"]],
            ),
        )
        if download_already_attempted:
            log.info("[%s]: Already downloaded. Skipping!", m["path"])
            continue

        if args.profile in (DBType.audio, DBType.video):
            try:
                tube_backend.yt(args, m)
            except Exception:
                print("db:", args.database)
                raise
        else:
            raise NotImplementedError


def dl_block(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(
        SC.block,
        usage=r"""library block database [playlists ...]

    Blocklist specific URLs (eg. YouTube channels, etc). With YT URLs this will block
    videos from the playlist uploader

        library block dl.db https://annoyingwebsite/etc/

    Use with the all-deleted-playlists flag to delete any previously downloaded files from the playlist uploader

        library block dl.db --all-deleted-playlists https://annoyingwebsite/etc/
    """,
    )

    if not any([args.playlists, args.all_deleted_playlists]):
        raise RuntimeError("Specific URLs or --all-deleted-playlists must be supplied")

    log.info(utils.dict_filter_bool(args.__dict__))
    args.category = consts.BLOCK_THE_CHANNEL
    args.extra_playlist_data = {"time_deleted": consts.APPLICATION_START}
    args.extra_media_data = {"time_deleted": consts.APPLICATION_START}
    for p in args.playlists:
        tube_backend.process_playlist(args, p, tube_backend.tube_opts(args, func_opts={"playlistend": 30}))

    if args.playlists:
        with args.db.conn:
            args.db.conn.execute(
                f"""UPDATE playlists
                SET time_deleted={consts.APPLICATION_START}
                ,   category='{consts.BLOCK_THE_CHANNEL}'
                WHERE path IN ("""
                + ",".join(["?"] * len(args.playlists))
                + ")",
                (*args.playlists,),
            )

    paths_to_delete = [
        d["path"]
        for d in args.db.query(
            """SELECT path FROM media
        WHERE time_downloaded > 0
        AND playlist_path IN ("""
            + ",".join(["?"] * len(args.playlists))
            + ")",
            (*args.playlists,),
        )
    ]

    if args.all_deleted_playlists:
        paths_to_delete = [
            d["path"]
            for d in args.db.query(
                """SELECT path FROM media
            WHERE time_downloaded > 0
            AND playlist_path IN (
                select path from playlists where time_deleted > 0
            ) """,
            )
        ]

    if paths_to_delete:
        print(paths_to_delete)
        if not consts.PYTEST_RUNNING and utils.confirm("Delete?"):
            player.delete_media(args, paths_to_delete)
