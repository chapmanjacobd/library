import argparse, os, sys
from typing import List, Tuple

from rich.prompt import Confirm

from xklb import consts, db, play_actions, player, stats, tube_backend, utils
from xklb.consts import SC, DBType
from xklb.utils import log


def parse_args(action, usage):
    parser = argparse.ArgumentParser(prog="library " + action, usage=usage)

    subp_profile = parser.add_mutually_exclusive_group()
    subp_profile.add_argument(
        "--audio", "-A", action="store_const", dest="profile", const=DBType.audio, help="Use audio downloader"
    )
    subp_profile.add_argument(
        "--video", "-V", action="store_const", dest="profile", const=DBType.video, help="Use video downloader"
    )
    subp_profile.add_argument(
        "--image", "-I", action="store_const", dest="profile", const=DBType.image, help="Use image downloader"
    )

    parser.add_argument(
        "--dl-config",
        "-dl-config",
        nargs=1,
        action=utils.argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend downloader configuration",
    )
    parser.add_argument("--extra-media-data", default={}, nargs=1, action=utils.argparse_dict, metavar="KEY=VALUE")
    parser.add_argument("--extra-playlist-data", default={}, nargs=1, action=utils.argparse_dict, metavar="KEY=VALUE")
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")

    parser.add_argument("--prefix", default=os.getcwd(), help=argparse.SUPPRESS)
    parser.add_argument("--ext", default="DEFAULT")
    parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
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

    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("playlists", nargs="*", help=argparse.SUPPRESS)

    args = parser.parse_args()
    if action == SC.download:
        if args.duration:
            args.duration = play_actions.parse_duration(args)

        if not args.profile and not args.print:
            print('Download profile must be specified. Use one of: --video --audio')
            raise SystemExit(1)

    if args.db:
        args.database = args.db
    args.db = db.connect(args)

    args.playlists = utils.conform(args.playlists)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def construct_query(args) -> Tuple[str, dict]:
    m_columns = args.db["media"].columns_dict
    pl_columns = args.db["playlists"].columns_dict

    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)

    cf.extend([" and " + w for w in args.where])

    play_actions.construct_search_bindings(args, bindings, cf, m_columns)

    cf.append(
        f"""and cast(STRFTIME('%s',
          datetime( time_modified, 'unixepoch', '+{args.retry_delay}')
        ) as int) < STRFTIME('%s', datetime()) """
    )

    if "uploader" in m_columns:
        cf.append(
            f"and media.uploader not in (select uploader from playlists where category='{consts.BLOCK_THE_CHANNEL}')"
        )

    args.sql_filter = " ".join(cf)
    args.sql_filter_bindings = bindings

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    query = f"""select
            media.path
            {', playlist_path' if 'playlist_path' in m_columns else ''}
            , media.title
            {', media.duration' if 'duration' in m_columns else ''}
            , media.time_created
            {', media.size' if 'size' in m_columns else ''}
            {', media.id' if 'id' in m_columns else ''}
            {', p.dl_config' if 'dl_config' in pl_columns else ''}
            , coalesce(p.category, p.ie_key) category
        FROM media
        JOIN playlists p on {db.get_playlists_join(args)}
        WHERE 1=1
            and (media.time_downloaded=0 OR media.time_modified > media.time_downloaded)
            and media.time_deleted=0
            and p.time_deleted=0
            {'AND (score IS NULL OR score > 7)' if 'score' in m_columns else ''}
            {'AND (upvote_ratio IS NULL OR upvote_ratio > 0.73)' if 'upvote_ratio' in m_columns else ''}
            {args.sql_filter}
        ORDER BY 1=1
            {', ' + args.sort if args.sort else ''}
            , play_count
            , random()
    {LIMIT}
    """

    return query, bindings


def process_downloadqueue(args) -> List[dict]:
    query, bindings = construct_query(args)

    if args.print:
        player.printer(args, query, bindings)
        return []

    media = list(args.db.query(*construct_query(args)))
    if not media:
        utils.no_media_found()

    return media


def dl_download(args=None) -> None:
    if args:
        sys.argv[1:] = args

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
    media = process_downloadqueue(args)
    for m in media:
        if args.safe and not tube_backend.is_supported(m["path"]):
            log.warning("[%s]: Unsupported URL (safe_mode)", m["path"])
            continue

        # check again in case it was already completed by another process
        path = list(args.db.query("select path from media where path=?", [m["path"]]))
        if not path:
            log.info("[%s]: Already downloaded. Skipping!", m["path"])
            continue

        if args.profile in (DBType.audio, DBType.video):
            tube_backend.yt(args, m)
        else:
            raise NotImplementedError


def dl_block(args=None) -> None:
    if args:
        sys.argv[1:] = args

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
        raise Exception("Specific URLs or --all-deleted-playlists must be supplied")

    log.info(utils.dict_filter_bool(args.__dict__))
    args.category = consts.BLOCK_THE_CHANNEL
    args.extra_playlist_data = dict(time_deleted=consts.NOW)
    args.extra_media_data = dict(time_deleted=consts.NOW)
    for p in args.playlists:
        tube_backend.process_playlist(args, p, tube_backend.tube_opts(args, func_opts={"playlistend": 30}))

    if args.playlists:
        with args.db.conn:
            args.db.conn.execute(
                f"""UPDATE playlists
                SET time_deleted={consts.NOW}
                ,   category='{consts.BLOCK_THE_CHANNEL}'
                WHERE path IN ("""
                + ",".join(["?"] * len(args.playlists))
                + ")",
                (*args.playlists,),
            )

    paths_to_delete = [
        d["path"]
        for d in args.db.query(
            f"""SELECT path FROM media
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
                f"""SELECT path FROM media
            WHERE time_downloaded > 0
            AND playlist_path IN (
                select path from playlists where time_deleted > 0
            ) """
            )
        ]

    if paths_to_delete:
        print(paths_to_delete)
        if not consts.PYTEST_RUNNING and Confirm.ask("Delete?"):
            player.delete_media(args, paths_to_delete)
