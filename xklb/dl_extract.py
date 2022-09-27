import argparse, os, sqlite3, sys
from pathlib import Path
from typing import List

import gallery_dl as gdl
import yt_dlp
from rich.prompt import Confirm

from xklb import db, paths, player, tube_actions, tube_extract, utils
from xklb.dl_config import yt_meaningless_errors, yt_recoverable_errors, yt_unrecoverable_errors
from xklb.utils import log


class DSC:
    dladd = "dladd"
    dlupdate = "dlupdate"
    download = "download"
    block = "block"


class DLProfile:
    audio = "audio"
    video = "video"
    image = "image"


def parse_args(action, usage):
    parser = argparse.ArgumentParser(prog="library " + action, usage=usage)

    subp_profile = parser.add_mutually_exclusive_group()
    subp_profile.add_argument(
        "--audio", action="store_const", dest="profile", const=DLProfile.audio, help="Use audio downloader"
    )
    subp_profile.add_argument(
        "--video", action="store_const", dest="profile", const=DLProfile.video, help="Use video downloader"
    )
    subp_profile.add_argument(
        "--image", action="store_const", dest="profile", const=DLProfile.image, help="Use image downloader"
    )

    parser.add_argument(
        "--dl-config",
        "-dl-config",
        nargs=1,
        action=utils.argparse_dict,
        default={},
        metavar="KEY=VALUE",
        help="Add key/value pairs to override or extend downloader configuration",
    )
    parser.add_argument("--extra-media-data", default={}, nargs=1, action=utils.argparse_dict, metavar="KEY=VALUE")
    parser.add_argument("--extra-playlist-data", default={}, nargs=1, action=utils.argparse_dict, metavar="KEY=VALUE")
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    if action in [DSC.dladd, DSC.dlupdate, DSC.block]:
        parser.add_argument("--extra", "-extra", action="store_true", help="Get full metadata (takes a lot longer)")
        parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
        parser.add_argument(
            "--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters"
        )
    if action == DSC.block:
        parser.add_argument("--all-deleted-playlists", "-a", action="store_true", help=argparse.SUPPRESS)
    if action in [DSC.dladd, DSC.dlupdate]:
        parser.add_argument("--category", "-c", help=argparse.SUPPRESS)
    if action == DSC.download:
        parser.add_argument("--prefix", default=os.getcwd(), help=argparse.SUPPRESS)
        parser.add_argument("--ext", default="DEFAULT")
        parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?", default="dl.db", help=argparse.SUPPRESS)
    if action == DSC.dladd:
        parser.add_argument("playlists", nargs="+", help=argparse.SUPPRESS)
    elif action == DSC.block:
        parser.add_argument("playlists", nargs="+", help=argparse.SUPPRESS)
    elif action == DSC.dlupdate:
        parser.add_argument("playlists", nargs="*", help=argparse.SUPPRESS)
    elif action == DSC.download:
        parser.add_argument("playlists", nargs="*", help=argparse.SUPPRESS)

    args = parser.parse_args()
    return args


def dl_add(args=None) -> None:
    """
    TODO:
        test dladd playlists of playlists, auto expand
        auto-detect reddit, use bdfr
        option for immediate download? (bandcamp, short-term valid URLs)
    """

    if args:
        sys.argv[1:] = args

    args = parse_args(
        DSC.dladd,
        usage=r"""library dladd [--audio | --video | --image] -c CATEGORY [database] playlists ...

    Tube and download databases are designed to be cross-compatible, but you will need to
    run dladd once first with a valid URL for the extra dl columns to be added.
    The supplied download profile and category of that first run will be copied to the existing rows.

    Create a dl database / add links to an existing database

        library dladd Educational dl.db https://www.youdl.com/c/BranchEducation/videos

    To download audio you must make the download profile (downloader) explicit with `--audio`

        library dladd --audio Educational dl.db https://www.youdl.com/c/BranchEducation/videos

    If you include more than one URL, you must specify the database

        library dladd 71_Mealtime_Videos dl.db (cat ~/.jobs/todo/71_Mealtime_Videos)

    Files will be saved to <lb download prefix>/<lb dladd category>/

        For example:
        library dladd Cool ...
        library download D:\'My Documents'\ ...
        Media will be downloaded to 'D:\My Documents\Cool\'
    """,
    )
    paths.check_mount(args)

    gdl.config.load()  # load default config files

    playlists = tube_extract.get_playlists(args)
    for path in args.playlists:
        saved_dl_config = tube_extract.get_playlist_dl_config(playlists, path)
        if saved_dl_config:
            log.info("[%s]: Updating known playlist", path)

        if args.safe and not tube_extract.is_supported(path):
            log.warning("[%s]: Unsupported playlist (safe_mode)", path)
            continue

        if args.profile is None:
            if tube_extract.is_supported(path):
                args.profile = DLProfile.video
            elif gdl.extractor.find(path):
                args.profile = DLProfile.image
            else:
                raise Exception(
                    f"Download profile '{args.profile}' could not be detected. Specify using `--audio`, `--video`, or `--image`"
                )

        args.extra_media_data = {"is_downloaded": 0, **args.extra_media_data}
        args.extra_playlist_data = {"category": args.category, "profile": args.profile, **args.extra_playlist_data}
        if args.profile in [DLProfile.audio, DLProfile.video]:
            tube_extract.process_playlist(
                args,
                path,
                ydl_opts=tube_actions.ydl_opts(
                    args, playlist_opts=saved_dl_config, func_opts={"ignoreerrors": "only_download"}
                ),
            )

        elif args.profile == DLProfile.image:
            job = gdl.job.DataJob(path)
            job.run()
            urls = job.data
            raise
            # TODO: save gallery-dl data to the database
            # gdl.config.set(("extractor",), "base-directory", "/tmp/")
            # gdl.job.DownloadJob(path)
        else:
            raise Exception(f"Download profile {args.profile} not implemented")

        try:
            with args.db.conn:
                if args.category:
                    args.db.execute("UPDATE playlists SET category=? WHERE category is NULL", [args.category])
                if args.profile:
                    args.db.execute("UPDATE playlists SET profile=? WHERE profile is NULL", [args.profile])
        except sqlite3.OperationalError as e:
            log.warning("Could not update playlists table: %s", e)
            pass

    db.optimize(args)


def dl_update(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        DSC.dlupdate,
        usage=r"""library dlupdate [--audio | --video | --image] -c CATEGORY [database] playlists ...

    Similar to tubeupdate, get new content of existing saved playlists

        library dlupdate dl.db

    By default it will iterate through all your saved playlists but if you only
    care of a specific profile, category, or playlist then make it known and
    the updating will be constrained to your desired scope.

        library dlupdate --audio educational dl.db

    A playlist can only have one active profile and category so referencing
    a specific playlist is maximally specific.

        library dlupdate dl.db https://www.youdl.com/c/BranchEducation/videos

    """,
    )

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))

    gdl.config.load()  # load default config files

    # TODO: Profile.image
    # TODO: reddit
    playlists = tube_extract.get_playlists(args, cols="path, profile, dl_config", constrain=True)
    video_playlists = [d for d in playlists if d["profile"] == DLProfile.video]
    audio_playlists = [d for d in playlists if d["profile"] == DLProfile.audio]
    tube_playlists = audio_playlists + video_playlists
    tube_extract.show_unknown_playlist_warning(args, tube_playlists, DSC.dladd)
    tube_extract.update_playlists(args, tube_playlists)


def dl_block(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        DSC.block,
        usage=r"""library block database [playlists ...]

    Blocklist specific URLs (eg. YouTube channels, etc). With YT URLs this will block
    videos from the playlist uploader

        library block dl.db https://annoyingwebsite/etc/

    Use with the all-deleted-playlists flag to delete any previously downloaded files from the playlist uploader

        library block dl.db --all-deleted-playlists https://annoyingwebsite/etc/
    """,
    )

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)

    if not any([args.playlists, args.all_deleted_playlists]):
        raise Exception("Specific URLs or --all-deleted-playlists must be supplied")

    log.info(utils.dict_filter_bool(args.__dict__))
    args.extra_playlist_data = dict(is_deleted=1, category=paths.BLOCK_THE_CHANNEL)
    args.extra_media_data = dict(is_deleted=1)
    for p in args.playlists:
        tube_extract.process_playlist(args, p, tube_actions.ydl_opts(args, func_opts={"playlistend": 30}))

    if args.playlists:
        with args.db.conn:
            args.db.execute(
                f"""UPDATE playlists
                SET is_deleted=1
                ,   category='{paths.BLOCK_THE_CHANNEL}'
                WHERE path IN ("""
                + ",".join(["?"] * len(args.playlists))
                + ")",
                (*args.playlists,),
            )

    paths_to_delete = [
        d["path"]
        for d in args.db.query(
            f"""SELECT path FROM media
        WHERE is_downloaded=1
        AND playlist_path IN ("""
            + ",".join(["?"] * len(args.playlists))
            + ")",
            (*args.playlists,),
        )
    ]

    if args.all_deleted_playlists:
        paths_to_delete = [
            d["path"]
            for d in args.db.query(
                f"""SELECT path FROM media
            WHERE is_downloaded=1
            AND playlist_path IN (
                select path from playlists where is_deleted=1
            ) """
            )
        ]

    if len(paths_to_delete) > 0:
        print(paths_to_delete)
        if not utils.PYTEST_RUNNING and Confirm.ask("Delete?"):
            player.delete_media(args, paths_to_delete)


def construct_query(args):
    return (
        f"""select
            media.path
            , playlists.dl_config
            , playlists.category
            , playlists.profile
        from media
        join playlists on playlists.path = media.playlist_path
        where 1=1
            and is_downloaded=0
            and media.is_deleted=0
            and playlists.is_deleted=0
            and media.uploader not in (select uploader from playlists where category='{paths.BLOCK_THE_CHANNEL}')
        order by
            random()
        """,
        [],
    )


def process_downloadqueue(args) -> List[dict]:
    query, bindings = construct_query(args)

    if args.print:
        player.printer(args, query, bindings)
        return []

    media = list(args.db.query(*construct_query(args)))
    if len(media) == 0:
        print("No media found")
        exit(2)

    return media


def update_media(args, info, webpath) -> None:
    assert info["local_path"] != ""
    r = list(args.db.query("select * from media where path=?", [webpath]))
    assert len(r) == 1
    stub = r[0]

    entry = tube_extract.consolidate(stub["playlist_path"], info) or {}

    args.db["media"].insert(
        {
            **stub,
            **entry,
            "play_count": stub["play_count"],
            "time_played": stub["time_played"],
            "path": info["local_path"],
            "webpath": webpath,
            "is_downloaded": 1,
        },
        pk="path",
        alter=True,
        replace=True,
    )  # type: ignore

    args.db["media"].delete(webpath)


def yt(args, m, audio_only=False) -> None:
    ydl_log = {"warning": [], "error": []}

    class BadToTheBoneLogger:
        def debug(self, msg):
            if msg.startswith("[debug] "):
                pass
            else:
                self.info(msg)

        def info(self, msg):
            pass

        def warning(self, msg):
            ydl_log["warning"].append(msg)

        def error(self, msg):
            ydl_log["error"].append(msg)

    out_dir = lambda p: str(Path(args.prefix, m["category"], p))
    Path(out_dir("tunnel_snakes_rule")).parent.mkdir(parents=True, exist_ok=True)
    ydl_opts = tube_actions.ydl_opts(
        args,
        func_opts={
            "logger": BadToTheBoneLogger(),
            "skip_download": False if not utils.PYTEST_RUNNING else True,
            "subtitlesformat": "srt/best",
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en.*", "EN.*"],
            "extract_flat": False,
            "lazy_playlist": False,
            "playlistend": 400,  # limit playlists of playlists for safety
            "postprocessors": [{"key": "FFmpegMetadata", "add_metadata": True}],
            "outtmpl": {
                "default": out_dir("%(title)s [%(id)s].%(ext)s"),
                "chapter": out_dir("%(title)s - %(section_number)03d %(section_title)s [%(id)s].%(ext)s"),
            },
        },
        playlist_opts=m["dl_config"],
    )

    if args.ext == "DEFAULT":
        if audio_only:
            args.ext = "opus"
        else:
            args.ext = None

    if audio_only:
        ydl_opts[
            "format"
        ] = "bestaudio[ext=opus]/bestaudio[ext=webm]/bestaudio[ext=ogg]/bestaudio[ext=oga]/bestaudio/best"
        ydl_opts["postprocessors"].append({"key": "FFmpegExtractAudio", "preferredcodec": args.ext})

    match_filters = ["live_status=?not_live"]
    match_filter_user_config = ydl_opts.get("match_filter")
    if match_filter_user_config is not None:
        match_filters.append(match_filter_user_config)
    ydl_opts["match_filter"] = yt_dlp.utils.match_filter_func(" & ".join(match_filters).split(" | "))

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(m["path"], download=True)
        if info is None:
            log.warning("[%s]: yt-dlp returned no info", m["path"])
            return

        if audio_only:
            info["local_path"] = ydl.prepare_filename({**info, "ext": args.ext})
        else:
            info["local_path"] = ydl.prepare_filename(info)

        ydl_errors = ydl_log["error"] + ydl_log["warning"]
        print(ydl_errors)
        ydl_errors = "\n".join([s for s in ydl_errors if not yt_meaningless_errors.match(s)])

        if len(ydl_log["error"]) == 0:
            log.info("[%s]: No news is good news", m["path"])
            update_media(args, info, m["path"])
        elif yt_recoverable_errors.match(ydl_errors):
            log.info("[%s]: Recoverable error matched. try again later", m["path"])
            return
        elif yt_unrecoverable_errors.match(ydl_errors):
            log.info("[%s]: Unrecoverable error matched. oi troi oi! nothing can be done", m["path"])
            update_media(args, info, m["path"])
        else:
            log.warning("[%s]: Unknown error. %s", m["path"], ydl_errors)


def dl_download(args=None) -> None:
    # TODO: scan downloaded file, add size, subtitle_count to media table
    if args:
        sys.argv[1:] = args

    args = parse_args(
        DSC.download,
        usage=r"""library download database [--prefix /mnt/d/] [playlists ...]

    Tube and download databases are designed to be cross-compatible, but you will need to
    run dladd once first with a valid URL for the extra dl columns to be added.
    The supplied download profile and category of that first run will be copied to the existing rows.

    Download stuff in a random order.

        library download dl.db --prefix ~/output/path/root/

    Download stuff in a random order, limited to the specified playlist URLs.

        library download dl.db https://www.youtube.com/c/BlenderFoundation/videos

    Files will be saved to <lb download prefix>/<lb download category>/

        For example:
        library dladd Cool ...
        library download D:\'My Documents'\ ...
        Media will be downloaded to 'D:\My Documents\Cool\'

    Print list of queued up downloads

        library download --print

    Print list of saved playlists

        library playlists dl.db -p a
    """,
    )
    paths.check_mount(args, mount_point=args.prefix)

    media = process_downloadqueue(args)
    for m in media:
        # check again in case it was already completed by another process
        is_downloaded = list(args.db.query("select is_downloaded from media where path=?", [m["path"]]))
        if is_downloaded[0]["is_downloaded"] == 1:
            log.info("[%s]: Already downloaded. Skipping!", m["path"])
            continue

        if m["profile"] == DLProfile.video:
            yt(args, m)
        elif m["profile"] == DLProfile.audio:
            yt(args, m, audio_only=True)
        # elif m['profile'] == DLProfile.image:
        else:
            raise NotImplementedError


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
