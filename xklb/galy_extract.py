import argparse, sys
from pathlib import Path

import gallery_dl as gdl

from xklb import consts, db, utils
from xklb.consts import SC
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

    if action in (SC.galyadd, SC.galyupdate):
        parser.add_argument("--category", "-c", help=argparse.SUPPRESS)

    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="video.db")
    if action in (SC.galyadd):
        parser.add_argument("playlists", nargs="+", help=argparse.SUPPRESS)

    args = parser.parse_args()
    args.action = action

    if args.db:
        args.database = args.db
    if action in (SC.galyadd):
        Path(args.database).touch()
    args.db = db.connect(args)

    if hasattr(args, "no_sanitize") and hasattr(args, "playlists") and not args.no_sanitize:
        args.playlists = [utils.sanitize_url(args, p) for p in args.playlists]

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def galy_add(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        SC.galyadd,
        usage=r"""library galyadd [--audio | --video] -c CATEGORY [database] playlists ...

    Create a dl database / add links to an existing database

        library galyadd -c Educational dl.db https://www.youdl.com/c/BranchEducation/videos

    If you include more than one URL, you must specify the database

        library galyadd 71_Mealtime_Videos dl.db (cat ~/.jobs/todo/71_Mealtime_Videos)

    Files will be saved to <lb download prefix>/<lb galyadd category>/

        For example:
        library galyadd Cool ...
        library download D:\'My Documents'\ ...
        Media will be downloaded to 'D:\My Documents\Cool\'

    Fetch extra metadata:

        By default galyadd will quickly add media at the expense of less metadata.
        If you plan on using `library download` then it doesn't make sense to use `--extra`.
        Downloading will add the extra metadata automatically to the database.
        You can always fetch more metadata later via galyupdate:
        library galyupdate tw.db --extra
    """,
    )
    for path in args.playlists:

        gdl.config.load()  # load default config files
        job = gdl.job.DataJob(path)
        job.run()
        urls = job.data
        raise
        # TODO: save gallery-dl data to the database
        # gdl.config.set(("extractor",), "base-directory", "/tmp/")
        # gdl.job.DownloadJob(path)
