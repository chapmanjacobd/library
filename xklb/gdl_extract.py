import argparse, sys
from pathlib import Path

from xklb import db_media, db_playlists, gdl_backend, usage
from xklb.utils import arg_utils, consts, db_utils, iterables, objects, path_utils, processes
from xklb.utils.consts import SC
from xklb.utils.log_utils import log


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library " + action,
        usage=usage,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--extractor-config",
        "-extractor-config",
        nargs=1,
        action=arg_utils.ArgparseDict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default downloader configuration",
    )
    parser.add_argument("--download-archive", default="~/.local/share/gallerydl.sqlite3")
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters")
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Fetch metadata for paths even if they are already in the media table",
    )
    parser.add_argument("--extra-media-data", default={}, nargs=1, action=arg_utils.ArgparseDict, metavar="KEY=VALUE")
    parser.add_argument(
        "--extra-playlist-data",
        default={},
        nargs=1,
        action=arg_utils.ArgparseDict,
        metavar="KEY=VALUE",
    )
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--timeout", "-T", help="Quit after x minutes")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    if action == SC.galleryadd:
        parser.add_argument("--insert-only", action="store_true")
        parser.add_argument("--insert-only-playlists", action="store_true")
        parser.add_argument("playlists", nargs="*", action=arg_utils.ArgparseArgsOrStdin, help=argparse.SUPPRESS)

    args = parser.parse_intermixed_args()
    args.action = action

    if args.db:
        args.database = args.db
    if action == SC.galleryadd:
        Path(args.database).touch()
    args.db = db_utils.connect(args)

    if hasattr(args, "playlists"):
        args.playlists = list(set(s.strip() for s in args.playlists))
        if not args.no_sanitize:
            args.playlists = [path_utils.sanitize_url(args, p) for p in args.playlists]
        args.playlists = iterables.conform(args.playlists)

    processes.timeout(args.timeout)

    args.profile = consts.DBType.image
    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def gallery_add(args=None) -> None:
    if args:
        sys.argv = ["galleryadd", *args]

    args = parse_args(SC.galleryadd, usage=usage.galleryadd)

    if args.insert_only:
        args.db["media"].insert_all(
            [{"path": p, "time_created": consts.APPLICATION_START} for p in args.playlists],
            alter=True,
            ignore=True,
            pk="path",
        )
    elif args.insert_only_playlists:
        args.db["playlists"].insert_all(
            [{"path": p, "time_created": consts.APPLICATION_START} for p in args.playlists],
            alter=True,
            ignore=True,
            pk="path",
        )
    else:
        known_playlists = set()
        if not args.force and len(args.playlists) > 9:
            known_playlists = db_media.get_paths(args)

        for path in args.playlists:
            if path in known_playlists:
                log.info("[%s]: Already added. Skipping!", path)
                continue

            if args.safe and not gdl_backend.is_supported(args, path):
                log.info("[%s]: Skipping unsupported playlist (safe_mode)", path)
                continue

            gdl_backend.get_playlist_metadata(args, path)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def gallery_update(args=None) -> None:
    if args:
        sys.argv = ["galleryupdate", *args]

    args = parse_args(SC.galleryupdate, usage=usage.galleryupdate)

    gdl_playlists = db_playlists.get_all(
        args,
        sql_filters=["AND extractor_key NOT IN ('Local', 'reddit_praw_redditor', 'reddit_praw_subreddit')"],
    )
    for d in gdl_playlists:
        gdl_backend.get_playlist_metadata(args, d["path"])
