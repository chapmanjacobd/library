import argparse, sys
from pathlib import Path

from xklb import db, tube_backend, utils
from xklb.utils import log


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library tube" + action, usage=usage)

    parser.add_argument(
        "--dl-config",
        "-dl-config",
        nargs=1,
        action=utils.argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default downloader configuration",
    )
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters")
    parser.add_argument("--extra", "-extra", action="store_true", help="Get full metadata (takes a lot longer)")
    parser.add_argument("--extra-media-data", default={})
    parser.add_argument("--extra-playlist-data", default={})
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="tube.db")
    if action == "add":
        parser.add_argument("playlists", nargs="+")
    elif action == "update":
        parser.add_argument("--optimize", action="store_true", help="Optimize Database")

    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def tube_add(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        "add",
        usage="""library tubeadd [database] playlists ...

    Create a tube database / add playlists or videos to an existing database

        library tubeadd educational.db https://www.youtube.com/c/BranchEducation/videos

    Fetch extra metadata:

        By default tubeadd will quickly add media.
        You can always fetch more metadata later via tubeupdate.

        library tubeupdate tw.db --extra
""",
    )
    for path in args.playlists:
        if args.safe and not tube_backend.is_supported(path):
            log.warning("[%s]: Unsupported playlist (safe_mode)", path)
            continue

        tube_backend.process_playlist(args, path, tube_backend.tube_opts(args))

        if args.extra:
            log.warning("[%s]: Getting extra metadata", path)
            tube_backend.get_extra_metadata(args, path)


def tube_update(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        "update",
        usage="""usage: library tubeupdate [--optimize] [database]

    Fetch the latest videos from every playlist in your database

        library tubeupdate educational.db

    Or limit to specific ones...

        library tubeupdate educational.db https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos ...

    Run with --optimize to add indexes (might speed up searching but the size will increase):

        library tubeupdate --optimize examples/music.tl.db ''

    Fetch extra metadata:

        By default tubeupdate will quickly add media.
        You can run with --extra to fetch more details: (best resolution width, height, subtitle tags, etc)

        library tubeupdate educational.db --extra https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos
""",
    )
    playlists = tube_backend.get_playlists(args)
    tube_backend.update_playlists(args, playlists)

    db.optimize(args)
