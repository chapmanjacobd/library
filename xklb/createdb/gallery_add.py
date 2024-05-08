import argparse, sys
from pathlib import Path

from xklb import usage
from xklb.createdb import gallery_backend
from xklb.mediadb import db_media, db_playlists
from xklb.utils import arg_utils, arggroups, argparse_utils, consts, db_utils
from xklb.utils.consts import SC
from xklb.utils.log_utils import log


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(
        prog="library " + action,
        usage=usage,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    arggroups.extractor(parser)
    arggroups.download(parser)
    parser.set_defaults(download_archive=str(Path("~/.local/share/gallerydl.sqlite3").expanduser().resolve()))

    arggroups.debug(parser)

    arggroups.database(parser)
    if action == SC.gallery_add:
        arggroups.paths_or_stdin(parser)

    args = parser.parse_intermixed_args()
    args.action = action
    args.profile = consts.DBType.image

    arggroups.extractor_post(args)

    arggroups.args_post(args, parser, create_db=action == SC.gallery_add)
    return args


def gallery_add(args=None) -> None:
    if args:
        sys.argv = ["galleryadd", *args]

    args = parse_args(SC.gallery_add, usage=usage.gallery_add)
    paths = arg_utils.gen_paths(args)

    if args.insert_only:
        args.db["media"].insert_all(
            [{"path": p, "time_created": consts.APPLICATION_START} for p in paths],
            alter=True,
            ignore=True,
            pk="path",
        )
    elif args.insert_only_playlists:
        args.db["playlists"].insert_all(
            [{"path": p, "time_created": consts.APPLICATION_START} for p in paths],
            alter=True,
            ignore=True,
            pk="path",
        )
    else:
        paths = list(paths)
        known_playlists = set()
        if not args.force and len(paths) > 9:
            known_playlists = db_media.get_paths(args)

        for path in paths:
            if path in known_playlists:
                log.info("[%s]: Already added. Skipping!", path)
                continue

            if args.safe and not gallery_backend.is_supported(args, path):
                log.info("[%s]: Skipping unsupported playlist (safe_mode)", path)
                continue

            gallery_backend.get_playlist_metadata(args, path)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def gallery_update(args=None) -> None:
    if args:
        sys.argv = ["galleryupdate", *args]

    args = parse_args(SC.gallery_update, usage=usage.gallery_update)

    gdl_playlists = db_playlists.get_all(
        args,
        sql_filters=["AND extractor_key NOT IN ('Local', 'reddit_praw_redditor', 'reddit_praw_subreddit')"],
    )
    for d in gdl_playlists:
        gallery_backend.get_playlist_metadata(args, d["path"])
