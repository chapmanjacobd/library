import argparse, sys
from pathlib import Path

from xklb import db_media, db_playlists, tube_backend, usage
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
    arggroups.download_subtitle(parser)
    parser.set_defaults(download_archive=str(Path("~/.local/share/yt_archive.txt").expanduser().resolve()))

    arggroups.debug(parser)

    arggroups.database(parser)
    if action == SC.tubeadd:
        parser.add_argument(
            "playlists", nargs="*", default=argparse_utils.STDIN_DASH, action=argparse_utils.ArgparseArgsOrStdin
        )

    args = parser.parse_intermixed_args()
    args.action = action

    if action == SC.tubeadd:
        Path(args.database).touch()
    args.db = db_utils.connect(args)

    if hasattr(args, "playlists"):
        args.playlists = list({s.strip() for s in args.playlists})
        if not args.no_sanitize:
            args.playlists = [path_utils.sanitize_url(args, p) for p in args.playlists]
        args.playlists = iterables.conform(args.playlists)

    processes.timeout(args.timeout)

    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def tube_add(args=None) -> None:
    if args:
        sys.argv = ["tubeadd", *args]

    args = parse_args(SC.tubeadd, usage=usage.tubeadd)

    if args.insert_only:
        args.db["media"].insert_all(
            [
                {
                    "path": p,
                    "time_created": consts.APPLICATION_START,
                    "time_modified": 0,
                    "time_deleted": 0,
                }
                for p in args.playlists
            ],
            alter=True,
            ignore=True,
            pk="id",
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
            if args.safe and not tube_backend.is_supported(path):
                log.info("[%s]: Skipping unsupported playlist (safe_mode)", path)
                continue

            if path in known_playlists:
                log.info("[%s]: Already added. Skipping!", path)
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

    args = parse_args(SC.tubeupdate, usage=usage.tubeupdate)
    tube_playlists = db_playlists.get_all(
        args,
        sql_filters=["AND extractor_key NOT IN ('Local', 'reddit_praw_redditor', 'reddit_praw_subreddit')"],
    )
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
