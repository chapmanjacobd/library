import argparse, sys
from pathlib import Path

from xklb import consts, db, gdl_backend, media, playlists, usage, utils
from xklb.consts import SC
from xklb.utils import log


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
        action=utils.ArgparseDict,
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
    parser.add_argument("--extra-media-data", default={}, nargs=1, action=utils.ArgparseDict, metavar="KEY=VALUE")
    parser.add_argument("--extra-playlist-data", default={}, nargs=1, action=utils.ArgparseDict, metavar="KEY=VALUE")
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--timeout", "-T", help="Quit after x minutes")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    if action == SC.galleryadd:
        parser.add_argument("--playlist-files", action="store_true", help="Read playlists from text files")
        parser.add_argument("playlists", nargs="+", help=argparse.SUPPRESS)

    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db
    if action == SC.galleryadd:
        Path(args.database).touch()
    args.db = db.connect(args)

    if hasattr(args, "playlists"):
        args.playlists = list(set(s.strip() for s in args.playlists))
        if not args.no_sanitize:
            args.playlists = [utils.sanitize_url(args, p) for p in args.playlists]
        args.playlists = utils.conform(args.playlists)

    utils.timeout(args.timeout)

    args.profile = consts.DBType.image
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def gallery_add(args=None) -> None:
    if args:
        sys.argv = ["galleryadd", *args]

    args = parse_args(SC.galleryadd, usage=usage.galleryadd)
    if args.playlist_files:
        args.playlists = list(utils.flatten([Path(p).read_text().splitlines() for p in args.playlists]))

    known_playlists = set()
    if not args.force and len(args.playlists) > 9:
        known_playlists = media.get_paths(args)

    added_media_count = 0
    for path in args.playlists:
        if path in known_playlists:
            log.info("[%s]: Already added. Skipping!", path)
            continue

        if args.safe and not gdl_backend.is_supported(args, path):
            log.info("[%s]: Skipping unsupported playlist (safe_mode)", path)
            continue

        added_media_count += gdl_backend.get_playlist_metadata(args, path)

    LARGE_NUMBER = 100_000
    if not args.db["media"].detect_fts() or added_media_count > LARGE_NUMBER:
        db.optimize(args)


def gallery_update(args=None) -> None:
    if args:
        sys.argv = ["galleryupdate", *args]

    args = parse_args(SC.galleryupdate, usage=usage.galleryupdate)

    for d in playlists.get_all(args):
        gdl_backend.get_playlist_metadata(args, d["path"])
