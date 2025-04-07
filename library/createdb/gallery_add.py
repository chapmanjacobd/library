import argparse, sys
from pathlib import Path

from library import usage
from library.createdb import gallery_backend
from library.mediadb import db_media, db_playlists
from library.utils import arggroups, argparse_utils, consts, db_utils, file_utils
from library.utils.consts import SC
from library.utils.log_utils import log


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.extractor(parser)
    arggroups.download(parser)
    parser.set_defaults(profile=consts.DBType.image)
    parser.set_defaults(download_archive=str(Path("~/.local/share/gallerydl.sqlite3").expanduser().resolve()))

    arggroups.debug(parser)

    arggroups.database(parser)
    if action == SC.gallery_add:
        arggroups.paths_or_stdin(parser)

    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=action == SC.gallery_add)

    arggroups.extractor_post(args)
    return args


def gallery_add(args=None) -> None:
    if args:
        sys.argv = ["galleryadd", *args]

    args = parse_args(SC.gallery_add, usage=usage.gallery_add)

    db_playlists.create(args)
    db_media.create(args)
    paths = file_utils.gen_paths(args)

    if args.no_extract:
        args.db["media"].insert_all(
            [{"path": p, "time_created": consts.APPLICATION_START} for p in paths],
            alter=True,
            ignore=True,
        )
    elif args.no_extract_playlists:
        args.db["playlists"].insert_all(
            [{"path": p, "time_created": consts.APPLICATION_START} for p in paths],
            alter=True,
            ignore=True,
        )
    else:
        paths = list(paths)
        known_playlists = set()
        if not args.force and len(paths) > 9:
            known_playlists = db_media.get_paths(args)

        for path in paths:
            if path in known_playlists:
                log.info("[%s]: Known already. Skipping!", path)
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
