import argparse, sys
from pathlib import Path

from xklb import consts, db, tube_backend, utils
from xklb.consts import SC, DBType
from xklb.utils import log


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library " + action, usage=usage)

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

    if action in (SC.tubeadd, SC.tubeupdate):
        parser.add_argument("--category", "-c", help=argparse.SUPPRESS)

    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="video.db")
    if action == SC.tubeadd:
        parser.add_argument("playlists", nargs="+", help=argparse.SUPPRESS)

    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db
    if action == SC.tubeadd:
        Path(args.database).touch()
    args.db = db.connect(args)

    if hasattr(args, "no_sanitize") and hasattr(args, "playlists") and not args.no_sanitize:
        args.playlists = [consts.sanitize_url(args, p) for p in args.playlists]
    if hasattr(args, "playlists"):
        args.playlists = utils.conform(args.playlists)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def tube_add(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        SC.tubeadd,
        usage=r"""library tubeadd [--audio | --video] -c CATEGORY [database] playlists ...

    Create a dl database / add links to an existing database

        library tubeadd -c Educational dl.db https://www.youdl.com/c/BranchEducation/videos

    If you include more than one URL, you must specify the database

        library tubeadd 71_Mealtime_Videos dl.db (cat ~/.jobs/todo/71_Mealtime_Videos)

    Files will be saved to <lb download prefix>/<lb tubeadd category>/

        For example:
        library tubeadd Cool ...
        library download D:\'My Documents'\ ...
        Media will be downloaded to 'D:\My Documents\Cool\'

    Fetch extra metadata:

        By default tubeadd will quickly add media at the expense of less metadata.
        If you plan on using `library download` then it doesn't make sense to use `--extra`.
        Downloading will add the extra metadata automatically to the database.
        You can always fetch more metadata later via tubeupdate:
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

    if not args.db["media"].detect_fts() or tube_backend.added_media_count > 100000:
        db.optimize(args)


def tube_update(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        SC.tubeupdate,
        usage="""library tubeupdate [--audio | --video] [-c CATEGORY] [database]

    Fetch the latest videos for every playlist saved in your database

        library tubeupdate educational.db

    Or limit to specific categories...

        library tubeupdate -c "Bob Ross" educational.db

    Run with --optimize to add indexes (might speed up searching but the size will increase):

        library tubeupdate --optimize examples/music.tl.db

    Fetch extra metadata:

        By default tubeupdate will quickly add media.
        You can run with --extra to fetch more details: (best resolution width, height, subtitle tags, etc)

        library tubeupdate educational.db --extra https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos
""",
    )
    playlists = db.get_playlists(args, constrain=True)
    tube_backend.update_playlists(args, playlists)
