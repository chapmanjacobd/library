import argparse, sys
from pathlib import Path

from xklb import db_media, db_playlists, gdl_backend, usage
from xklb.utils import arggroups, argparse_utils, consts, db_utils, iterables, objects, path_utils, processes
from xklb.utils.consts import SC
from xklb.utils.log_utils import log


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library " + action,
        usage=usage,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arggroups.extractor(parser)
    arggroups.download(parser)
    parser.set_defaults(download_archive=str(Path("~/.local/share/gallerydl.sqlite3").expanduser().resolve()))

    arggroups.debug(parser)

    arggroups.database(parser)
    if action == SC.galleryadd:
        parser.add_argument(
            "playlists", nargs="*", default=argparse_utils.STDIN_DASH, action=argparse_utils.ArgparseArgsOrStdin
        )

    args = parser.parse_intermixed_args()
    args.action = action

    if action == SC.galleryadd:
        Path(args.database).touch()
    args.db = db_utils.connect(args)

    if hasattr(args, "playlists"):
        args.playlists = list({s.strip() for s in args.playlists})
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
