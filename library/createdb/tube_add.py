import argparse, sys
from pathlib import Path

from library.createdb import tube_backend
from library.mediadb import db_media, db_playlists
from library.utils import arggroups, argparse_utils, consts, db_utils, shell_utils
from library.utils.consts import SC
from library.utils.log_utils import log

USAGE = {
    'tube_add': r"""library database add video [--safe] [--extra] [--subs] [--auto-subs] DATABASE URL ...

    Create a dl database / add links to an existing database

        library database add video dl.db https://www.youdl.com/c/BranchEducation/videos

    Add links from a line-delimited file

        cat ./my_yt_subscriptions.txt | library database add video reddit.db -

    Add metadata to links already in a database table

        library database add video --force reddit.db (sqlite-utils --raw-lines reddit.db 'select path from media')

    Fetch extra metadata

        By default tubeadd quickly adds media at the expense of less metadata.
        If you plan on using `library database download` then it doesn't make sense to use `--extra`.
        Downloading adds the extra metadata automatically to the database.
        You can fetch more metadata at any time via tubeupdate
        library database update video tw.db --extra
""",
    'tube_update': """library database update video [--audio | --video] DATABASE

    Fetch the latest videos for every playlist saved in your database

        library database update video educational.db

    Fetch extra metadata

        By default tubeupdate quickly adds media.
        You can run with --extra to fetch more details: (best resolution width, height, subtitle tags, etc)

        library database update video educational.db --extra https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos

    Remove duplicate playlists

        library database dedupe video.db playlists --bk extractor_playlist_id
""",
}


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.extractor(parser)
    arggroups.download(parser)
    arggroups.download_subtitle(parser)
    parser.set_defaults(download_archive=str(Path("~/.local/share/yt_archive.txt").expanduser().resolve()))

    arggroups.debug(parser)

    arggroups.database(parser)
    if action == SC.tube_add:
        arggroups.paths_or_stdin(parser)

    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=action == SC.tube_add)

    arggroups.extractor_post(args)

    return args


def tube_add(args=None) -> None:
    if args:
        sys.argv = ["tubeadd", *args]

    args = parse_args(SC.tube_add, usage=USAGE['tube_add'])
    paths = shell_utils.gen_paths(args)

    db_playlists.create(args)
    db_media.create(args)

    if args.no_extract:
        args.db["media"].insert_all(
            [
                {
                    "path": p,
                    "time_created": consts.APPLICATION_START,
                    "time_modified": 0,
                    "time_deleted": 0,
                }
                for p in paths
            ],
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
            if args.safe and not tube_backend.is_supported(path):
                log.info("[%s]: Skipping unsupported playlist (safe_mode)", path)
                continue

            if path in known_playlists:
                log.info("[%s]: Known already. Skipping!", path)
                continue

            tube_backend.get_playlist_metadata(args, path, tube_backend.tube_opts(args))

            if args.extra or args.subs or args.auto_subs:
                log.warning("[%s]: Getting extra metadata", path)
                tube_backend.get_extra_metadata(args, path)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def tube_update(args=None) -> None:
    if args:
        sys.argv = ["tubeupdate", *args]

    args = parse_args(SC.tube_update, usage=USAGE['tube_update'])

    tube_playlists = db_playlists.get_all(
        args,
        sql_filters=[
            "AND coalesce(extractor_key, '') NOT IN ('Local', 'reddit_praw_redditor', 'reddit_praw_subreddit')"
        ],
    )

    print("Checking", len(tube_playlists), "playlists for updates")
    for d in tube_playlists:
        tube_backend.get_playlist_metadata(
            args,
            d["path"],
            tube_backend.tube_opts(
                args,
                playlist_opts=d.get("extractor_config", "{}"),
                func_opts={"ignoreerrors": "only_download"},
            ),
        )

        if args.extra or args.subs or args.auto_subs:
            log.warning("[%s]: Getting extra metadata", d["path"])
            tube_backend.get_extra_metadata(args, d["path"], playlist_dl_opts=d.get("extractor_config", "{}"))
