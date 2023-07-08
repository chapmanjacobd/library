import argparse, sys
from pathlib import Path

from xklb import consts, db, media, playlists, tube_backend, usage, utils
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
    parser.add_argument("--download-archive", default="~/.local/share/yt_archive.txt")
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters")
    parser.add_argument("--extra", "-extra", action="store_true", help="Get full metadata (takes a lot longer)")
    parser.add_argument("--no-optimize", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Fetch metadata for paths even if they are already in the media table",
    )
    parser.add_argument("--subs", action="store_true")
    parser.add_argument("--auto-subs", "--autosubs", action="store_true")
    parser.add_argument("--subtitle-languages", "--subtitle-language", "--sl", action=utils.ArgparseList)
    parser.add_argument("--extra-media-data", default={}, nargs=1, action=utils.ArgparseDict, metavar="KEY=VALUE")
    parser.add_argument("--extra-playlist-data", default={}, nargs=1, action=utils.ArgparseDict, metavar="KEY=VALUE")
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--timeout", "-T", help="Quit after x minutes")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    if action == SC.tubeadd:
        parser.add_argument("--insert-only", action="store_true")
        parser.add_argument("--insert-only-playlists", action="store_true")
        parser.add_argument("playlists", nargs="*", action=utils.ArgparseArgsOrStdin, help=argparse.SUPPRESS)

    args = parser.parse_intermixed_args()
    args.action = action

    if args.db:
        args.database = args.db
    if action == SC.tubeadd:
        Path(args.database).touch()
    args.db = db.connect(args)

    if hasattr(args, "playlists"):
        args.playlists = list(set(s.strip() for s in args.playlists))
        if not args.no_sanitize:
            args.playlists = [utils.sanitize_url(args, p) for p in args.playlists]
        args.playlists = utils.conform(args.playlists)

    utils.timeout(args.timeout)

    args.profile = consts.DBType.video
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def tube_add(args=None) -> None:
    if args:
        sys.argv = ["tubeadd", *args]

    args = parse_args(SC.tubeadd, usage=usage.tubeadd)

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
            known_playlists = media.get_paths(args)

        for path in args.playlists:
            if args.safe and not tube_backend.is_supported(path):
                log.info("[%s]: Skipping unsupported playlist (safe_mode)", path)
                continue

            if path in known_playlists:
                log.info("[%s]: Already added. Skipping!", path)
                continue

            tube_backend.get_playlist_metadata(args, path, tube_backend.tube_opts(args))

            if args.extra:
                log.warning("[%s]: Getting extra metadata", path)
                tube_backend.get_extra_metadata(args, path)

    if not args.no_optimize and not args.db["media"].detect_fts():
        db.optimize(args)


def tube_update(args=None) -> None:
    if args:
        sys.argv = ["tubeupdate", *args]

    args = parse_args(SC.tubeupdate, usage=usage.tubeupdate)
    tube_playlists = playlists.get_all(
        args, sql_filters=["AND extractor_key NOT IN ('Local', 'reddit_praw_redditor', 'reddit_praw_subreddit')"]
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

        if args.extra:
            log.warning("[%s]: Getting extra metadata", d["path"])
            tube_backend.get_extra_metadata(args, d["path"], playlist_dl_opts=d.get("extractor_config", "{}"))
