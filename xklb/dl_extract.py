import argparse, sys
from pathlib import Path
from sqlite3 import OperationalError
from typing import List

import gallery_dl as gdl

from xklb import db, tube_extract, utils
from xklb.utils import log


def is_playlist_known(args, playlist_path) -> bool:
    try:
        known = args.db.execute("select 1 from playlists where path=?", [playlist_path]).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return known[0]


def is_video_known(args, playlist_path, path) -> bool:
    try:
        known = args.db.execute(
            "select 1 from media where playlist_path=? and path=?", [playlist_path, path]
        ).fetchone()
    except Exception:
        return False
    if known is None:
        return False
    return known[0]


def save_entries(args, entries) -> None:
    if entries:
        args.db["media"].insert_all(entries, pk="path", alter=True, replace=True)  # type: ignore


def get_playlists(args) -> List[dict]:
    try:
        known_playlists = list(args.db.query("select path, yt_dlp_config from playlists order by random()"))
    except OperationalError:
        known_playlists = []
    return known_playlists


class Profile:
    audio = "audio"
    video = "video"
    image = "image"


def dl_add(args=None):
    if args:
        sys.argv[1:] = args

    parser = argparse.ArgumentParser(
        prog="library dladd",
        usage=r"""library dladd [--audio | --video | --image] [database] category playlists ...

    Tube and download databases are designed to be cross-compatible, but you will need to
    run dladd once first with a valid URL for the extra dl columns to be added. The supplied download
    profile and category of this first run will be copied to the existing rows.

    Create a dl database / add links to an existing database

        library dladd educational dl.db https://www.youdl.com/c/BranchEducation/videos

    To download audio you must make the download profile explicit with `--audio`

        library dladd --audio educational dl.db https://www.youdl.com/c/BranchEducation/videos

    Files will be saved to <lb download prefix>/<lb dladd category>/

        For example:
        library dladd Cool ...
        library download D:\'My Documents'\ ...
        Media will be downloaded to 'D:\My Documents\Cool\'

    """,
    )
    parser.add_argument("database", nargs="?", default="dl.db")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("category")
    parser.add_argument("playlists", nargs="+")

    dl_profile = parser.add_mutually_exclusive_group()
    dl_profile.add_argument(
        "--audio", action="store_const", dest="dl_profile", const="a", help="Use audio download profile"
    )
    dl_profile.add_argument(
        "--video", action="store_const", dest="dl_profile", const="v", help="Use video download profile"
    )
    dl_profile.add_argument(
        "--image", action="store_const", dest="dl_profile", const="i", help="Use image download profile"
    )

    parser.add_argument(
        "--yt-dlp-config",
        "-yt-dlp-config",
        nargs=1,
        action=utils.argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend default yt-dlp configuration",
    )
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters")

    parser.add_argument("--extra-media-data", default={})
    parser.add_argument("--extra-playlist-data", default={})
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    if args.db:
        args.database = args.db

    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    gdl.config.load()  # load default config files

    playlists = get_playlists(args)
    for path in args.playlists:
        saved_yt_dlp_config = tube_extract.get_saved_yt_dlp_config(playlists, path)
        if saved_yt_dlp_config:
            log.info("[%s]: Updating known playlist", path)

        if args.safe and not tube_extract.is_supported(path):
            log.warning("[%s]: Unsupported playlist (safe_mode)", path)
            continue

        if args.dl_profile is None:
            if tube_extract.is_supported:
                args.dl_profile = "video"
            elif gdl.extractor.find(path):
                args.dl_profile = "photo"
        else:
            raise Exception(
                f"dl_profile {args.dl_profile} could not be detected. Please specify using `--audio`, `--video`, or `--image`"
            )

        args.extra_media_data = {"is_downloaded": 0}
        args.extra_playlist_data = {"category": args.category, "profile": args.dl_profile}
        if args.dl_profile in [Profile.audio, Profile.video]:
            tube_extract.process_playlist(args, path, ydl_opts=tube_extract.parse_ydl_opts(args, saved_yt_dlp_config))
        elif args.dl_profile == Profile.image:
            job = gdl.job.DataJob(path)
            job.run()
            urls = job.data
            raise
            # TODO: save gallery-dl data to the database
            # gdl.config.set(("extractor",), "base-directory", "/tmp/")
            # gdl.job.DownloadJob(path)
        else:
            raise Exception(f"dl_profile {args.dl_profile} not implemented")

        if "is_downloaded" not in args.db["media"].columns:
            args.db["media"].add_column("is_downloaded", int, not_null_default=0)  # type: ignore
        if "category" not in args.db["playlists"].columns:
            args.db["playlists"].add_column("category", str, not_null_default=args.category)  # type: ignore
            args.db["playlists"].add_column("profile", str, not_null_default=args.dl_profile)  # type: ignore
        db.optimize(args)


def parse_gallerydl_exit(ret_val: int) -> str:
    errors = []
    if ret_val & 1:
        errors.append("Unspecified Error")
    if ret_val & 2:
        errors.append("Cmdline Arguments")
    if ret_val & 4:
        errors.append("HTTP Error")
    if ret_val & 8:
        errors.append("Not Found / 404")
    if ret_val & 16:
        errors.append("Auth / Login")
    if ret_val & 32:
        errors.append("Format / Filter")
    if ret_val & 64:
        errors.append("No Extractor")
    if ret_val & 128:
        errors.append("OS Error")
    return "; ".join(errors)


"""
- dladd
    auto-detect reddit, use bdfr
    option for immediate download? (bandcamp, short-term valid URLs)

- dl
    args.prefix
    run dl-get-sounds,dl-get-video,dl-get-photo

{
    **ydl_opts,
    "format": "bestaudio[ext=opus]/bestaudio[ext=webm]/bestaudio[ext=ogg]/bestaudio[ext=oga]/bestaudio/best",
    "match_filter": "live_status=?not_live"
    "postprocessors": [
        {
            "key": "FFmpegMetadata",
            "add_metadata": True,
        },
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "opus",
        },
    ],
}

    after something is saved:
    - path: downloaded fs path
    - webpath: URL
    - is_downloaded = 1
    - scan downloaded file, add metadata to media table

"""


def dl_download(args=None):
    if args:
        sys.argv[1:] = args
