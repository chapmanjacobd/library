import argparse, sys
from pathlib import Path

from library import usage
from library.database.add import tube_backend
from library.database.manage import db_media, db_playlists
from library.utils import arggroups, argparse_utils, consts, db_utils, iterables, shell_utils
from library.utils.consts import DBType, SC
from library.utils.log_utils import log

MAX_PATHS_WITHOUT_FORCE = 9


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.extractor(parser)
    arggroups.download(
        parser,
        default=arggroups.default_profile(action),
        profiles=(DBType.audio, DBType.video),
    )
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

    args = parse_args(SC.tube_add, usage=usage.tube_add)
    paths = list(iterables.ordered_set(shell_utils.gen_paths(args)))

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
        known_playlists = set()
        retrieved_paths = set()
        if not args.force and len(paths) > MAX_PATHS_WITHOUT_FORCE:
            known_playlists = db_media.get_paths(args)

        for path in paths:
            if args.safe and not tube_backend.is_supported(path):
                log.info("[%s]: Skipping unsupported playlist (safe_mode)", path)
                continue

            if path in known_playlists:
                log.info("[%s]: Known already. Skipping!", path)
                continue

            if path in retrieved_paths:
                continue
            tube_backend.get_playlist_metadata(
                args,
                path,
                tube_backend.tube_opts(args),
                retrieved_paths=retrieved_paths,
            )

            if args.extra or args.subs or args.auto_subs:
                log.warning("[%s]: Getting extra metadata", path)
                tube_backend.get_extra_metadata(args, path)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def tube_update(args=None) -> None:
    if args:
        sys.argv = ["tubeupdate", *args]

    args = parse_args(SC.tube_update, usage=usage.tube_update)

    tube_playlists = db_playlists.get_all(
        args,
        sql_filters=[
            "AND coalesce(extractor_key, '') NOT IN ('Local', 'reddit_praw_redditor', 'reddit_praw_subreddit')"
        ],
    )

    print("Checking", len(tube_playlists), "playlists for updates")
    seen_paths = set()
    retrieved_paths = set()
    for d in tube_playlists:
        if d["path"] in seen_paths or d["path"] in retrieved_paths:
            continue
        seen_paths.add(d["path"])
        tube_backend.get_playlist_metadata(
            args,
            d["path"],
            tube_backend.tube_opts(
                args,
                playlist_opts=d.get("extractor_config", "{}"),
                func_opts={"ignoreerrors": "only_download"},
            ),
            retrieved_paths=retrieved_paths,
        )

        if args.extra or args.subs or args.auto_subs:
            log.warning("[%s]: Getting extra metadata", d["path"])
            tube_backend.get_extra_metadata(args, d["path"], playlist_dl_opts=d.get("extractor_config", "{}"))
