import argparse, csv, datetime, operator, os, sqlite3, sys
from copy import deepcopy
from io import StringIO
from pathlib import Path
from shlex import quote
from typing import List, Optional, Tuple

import gallery_dl as gdl
import yt_dlp
from rich.prompt import Confirm
from tabulate import tabulate

from xklb import consts, db, fs_extract, play_actions, player, tube_actions, tube_backend, utils
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
        "--audio", "-A", action="store_const", dest="profile", const=DLProfile.audio, help="Use audio downloader"
    )
    subp_profile.add_argument(
        "--video", "-V", action="store_const", dest="profile", const=DLProfile.video, help="Use video downloader"
    )
    subp_profile.add_argument(
        "--image", "-I", action="store_const", dest="profile", const=DLProfile.image, help="Use image downloader"
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

    if action in (DSC.dladd, DSC.dlupdate, DSC.block):
        parser.add_argument("--extra", "-extra", action="store_true", help="Get full metadata (takes a lot longer)")
        parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
        parser.add_argument(
            "--no-sanitize", "-s", action="store_true", help="Don't sanitize some common URL parameters"
        )
    if action == DSC.block:
        parser.add_argument("--all-deleted-playlists", "--all", action="store_true", help=argparse.SUPPRESS)
    if action in (DSC.dladd, DSC.dlupdate):
        parser.add_argument("--category", "-c", help=argparse.SUPPRESS)
    if action == DSC.download:
        parser.add_argument("--prefix", default=os.getcwd(), help=argparse.SUPPRESS)
        parser.add_argument("--ext", default="DEFAULT")
        parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)
        parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
        parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
        parser.add_argument(
            "--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS
        )
        parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
        parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
        parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
        parser.add_argument("--small", action="store_true", help="Prefer 480p-like")
        parser.add_argument(
            "--retry-delay",
            "-r",
            default="14 days",
            help="Must be specified in SQLITE Modifiers format: N hours, days, months, or years",
        )

    parser.add_argument("database", nargs="?", default="dl.db", help=argparse.SUPPRESS)
    if action == DSC.dladd:
        parser.add_argument("playlists", nargs="+", help=argparse.SUPPRESS)
    elif action == DSC.block:
        parser.add_argument("playlists", nargs="+", help=argparse.SUPPRESS)
    elif action == DSC.download:
        parser.add_argument("playlists", nargs="*", help=argparse.SUPPRESS)

    args = parser.parse_args()
    if action == DSC.download:
        if args.limit in ("inf", "all"):
            args.limit = None
        if args.duration:
            args.duration = play_actions.parse_duration(args)

    if args.db:
        args.database = args.db
    if action in (DSC.dladd, DSC.block):
        Path(args.database).touch()
    args.db = db.connect(args)

    if hasattr(args, "no_sanitize") and hasattr(args, "playlists") and not args.no_sanitize:
        args.playlists = [consts.sanitize_url(args, p) for p in args.playlists]

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def dl_add(args=None) -> None:
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

    gdl.config.load()  # load default config files

    for path in args.playlists:
        if args.safe and not tube_backend.is_supported(path):
            log.warning("[%s]: Unsupported playlist (safe_mode)", path)
            continue

        if args.profile is None:
            if tube_backend.is_supported(path):
                args.profile = DLProfile.video
            elif gdl.extractor.find(path):
                args.profile = DLProfile.image
            else:
                raise Exception(
                    f"Download profile '{args.profile}' could not be detected. Specify using `--audio`, `--video`, or `--image`"
                )

        args.extra_playlist_data = {"category": args.category, "profile": args.profile, **args.extra_playlist_data}
        if args.profile in (DLProfile.audio, DLProfile.video):
            tube_backend.process_playlist(
                args,
                path,
                ydl_opts=tube_backend.tube_opts(args, func_opts={"ignoreerrors": "only_download"}),
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


def dl_update(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        DSC.dlupdate,
        usage=r"""library dlupdate [--audio | --video | --image] [-c CATEGORY] [database]

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

    gdl.config.load()  # load default config files

    # TODO: Profile.image
    # TODO: reddit
    playlists = tube_backend.get_playlists(args, cols="path, profile, dl_config", constrain=True)
    video_playlists = [d for d in playlists if d["profile"] == DLProfile.video]
    audio_playlists = [d for d in playlists if d["profile"] == DLProfile.audio]
    tube_playlists = audio_playlists + video_playlists
    tube_backend.update_playlists(args, tube_playlists)


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

    if not any([args.playlists, args.all_deleted_playlists]):
        raise Exception("Specific URLs or --all-deleted-playlists must be supplied")

    log.info(utils.dict_filter_bool(args.__dict__))
    args.extra_playlist_data = dict(time_deleted=utils.NOW, category=consts.BLOCK_THE_CHANNEL)
    args.extra_media_data = dict(time_deleted=utils.NOW)
    for p in args.playlists:
        tube_backend.process_playlist(args, p, tube_backend.tube_opts(args, func_opts={"playlistend": 30}))

    if args.playlists:
        with args.db.conn:
            args.db.execute(
                f"""UPDATE playlists
                SET time_deleted={utils.NOW}
                ,   category='{consts.BLOCK_THE_CHANNEL}'
                WHERE path IN ("""
                + ",".join(["?"] * len(args.playlists))
                + ")",
                (*args.playlists,),
            )

    paths_to_delete = [
        d["path"]
        for d in args.db.query(
            f"""SELECT path FROM media
        WHERE time_downloaded > 0
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
            WHERE time_downloaded > 0
            AND playlist_path IN (
                select path from playlists where time_deleted > 0
            ) """
            )
        ]

    if paths_to_delete:
        print(paths_to_delete)
        if not utils.PYTEST_RUNNING and Confirm.ask("Delete?"):
            player.delete_media(args, paths_to_delete)


def construct_query(args) -> Tuple[str, dict]:
    cf = []
    bindings = {}

    if args.duration:
        cf.append(" and duration IS NOT NULL " + args.duration)

    cf.extend([" and " + w for w in args.where])

    play_actions.construct_search_bindings(
        args, bindings, cf, tube_actions.tube_include_string, tube_actions.tube_exclude_string
    )

    if not args.print:
        cf.append(
            f"""and cast(STRFTIME('%s',
                datetime( time_downloaded, 'unixepoch', '+{args.retry_delay}')
            ) as int) < STRFTIME('%s', datetime()) """
        )

    args.sql_filter = " ".join(cf)
    args.sql_filter_bindings = bindings

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""

    query = f"""select
            media.path
            , media.title
            , media.duration
            , media.time_created
            , playlists.dl_config
            , coalesce(playlists.category, playlists.ie_key) category
            , playlists.profile
        FROM media
        JOIN playlists on playlists.path = media.playlist_path
        WHERE 1=1
            and time_downloaded=0
            and media.time_deleted=0
            and playlists.time_deleted=0
            and media.uploader not in (select uploader from playlists where category='{consts.BLOCK_THE_CHANNEL}')
            {args.sql_filter}
        ORDER BY 1=1
            {', ' + args.sort if args.sort else ''}
            , play_count
            , random()
    {LIMIT}
    """

    return query, bindings


def printer(args, query, bindings) -> None:
    if "a" in args.print:
        query = f"""select
            "Aggregate" as path
            , sum(duration) duration
            , avg(duration) avg_duration
            , count(*) count
        from ({query}) """

    db_resp = list(args.db.query(query, bindings))
    if not db_resp:
        print("No media found")
        exit(2)

    if "d" in args.print:
        player.mark_media_deleted(args, list(map(operator.itemgetter("path"), db_resp)))
        if not "f" in args.print:
            return print(f"Removed {len(db_resp)} metadata records")

    if "w" in args.print:
        marked = player.mark_media_watched(args, list(map(operator.itemgetter("path"), db_resp)))
        if not "f" in args.print:
            return print(f"Marked {marked} metadata records as watched")

    if "f" in args.print:
        if args.limit == 1:
            f = db_resp[0]["path"]
            if not Path(f).exists():
                player.mark_media_deleted(args, f)
                return printer(args, query, bindings)
            print(quote(f))
        else:
            if not args.cols:
                args.cols = ["path"]

            selected_cols = [{k: d.get(k, None) for k in args.cols} for d in db_resp]
            virtual_csv = StringIO()
            wr = csv.writer(virtual_csv, quoting=csv.QUOTE_NONE)
            wr = csv.DictWriter(virtual_csv, fieldnames=args.cols)
            wr.writerows(selected_cols)

            virtual_csv.seek(0)
            for line in virtual_csv.readlines():
                if args.moved:
                    print(line.strip().replace(args.moved[0], "", 1))
                else:
                    print(line.strip())
    else:
        tbl = deepcopy(db_resp)
        utils.col_resize(tbl, "path", 22)
        utils.col_resize(tbl, "title", 18)

        utils.col_naturalsize(tbl, "size")
        utils.col_duration(tbl, "duration")
        utils.col_duration(tbl, "avg_duration")

        for t in (
            "time_modified",
            "time_created",
            "time_played",
            "time_valid",
            "time_partial_first",
            "time_partial_last",
        ):
            utils.col_naturaldate(tbl, t)

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))  # type: ignore


def process_downloadqueue(args) -> List[dict]:
    query, bindings = construct_query(args)

    if args.print:
        printer(args, query, bindings)
        return []

    media = list(args.db.query(*construct_query(args)))
    if not media:
        print("No media found")
        exit(2)

    return media


def update_media(
    args, webpath, info: Optional[dict] = None, db_type: Optional[fs_extract.DBType] = None, error=None, URE=False
) -> None:
    r = list(args.db.query("select * from media where path=?", [webpath]))
    assert len(r) == 1
    stub = r[0]

    if not info:
        args.db["media"].insert(
            {
                **stub,
                "time_downloaded": utils.NOW,
                "time_downloaded": 0,
                "time_deleted": utils.NOW if URE else 0,
                "error": error,
            },
            pk="path",
            alter=True,
            replace=True,
        )  # type: ignore
        return

    assert info["local_path"] != ""
    if Path(info["local_path"]).exists():
        fs_args = argparse.Namespace(
            db_type=db_type,
            scan_subtitles=True if db_type == fs_extract.DBType.video else False,
            delete_unplayable=False,
            ocr=False,
            speech_recognition=False,
        )
        fs_tags = fs_extract.extract_metadata(fs_args, info["local_path"]) or {}
    else:
        fs_tags = {}

    entry = tube_backend.consolidate(stub["playlist_path"], info) or {}
    args.db["media"].insert(
        {
            **stub,
            **entry,
            **fs_tags,
            "play_count": stub["play_count"],
            "time_played": stub["time_played"],
            "time_downloaded": utils.NOW,
            "webpath": webpath,
            "time_downloaded": utils.NOW if db_type else 0,
            "time_deleted": utils.NOW if URE else 0,
            "error": error,
        },
        pk="path",
        alter=True,
        replace=True,
    )  # type: ignore

    if fs_tags:
        args.db["media"].delete(webpath)


def yt(args, m) -> None:
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
    ydl_opts = tube_backend.tube_opts(
        args,
        func_opts={
            "subtitleslangs": ["en.*", "EN.*"],
            "extractor_args": {"youtube": {"skip": ["authcheck"]}},
            "logger": BadToTheBoneLogger(),
            "writesubtitles": True,
            "writeautomaticsub": True,
            "skip_download": True if utils.PYTEST_RUNNING else False,
            "subtitlesformat": "srt/best",
            "extract_flat": False,
            "lazy_playlist": False,
            "postprocessors": [{"key": "FFmpegMetadata"}, {"key": "FFmpegEmbedSubtitle"}],
            "restrictfilenames": True,
            "extractor_retries": 13,
            "retries": 13,
            "outtmpl": {
                "default": out_dir("%(uploader|uploader_id)s/%(title).200B_[%(id).60B].%(ext)s"),
                "chapter": out_dir(
                    "%(uploader|uploader_id)s/%(title).200B_%(section_number)03d_%(section_title)s_[%(id).60B].%(ext)s"
                ),
            },
        },
        playlist_opts=m["dl_config"],
    )

    download_archive = Path("~/.local/share/yt_archive.txt").resolve()
    if download_archive.exists():
        ydl_opts["download_archive"] = str(download_archive)
        ydl_opts["cookiesfrombrowser"] = (("firefox",),)

    if args.small:
        ydl_opts["format"] = "bestvideo[height<=576]+bestaudio/best[height<=576]/best"

    if args.ext == "DEFAULT":
        if m["profile"] == DLProfile.audio:
            args.ext = "opus"
        else:
            args.ext = None

    if m["profile"] == DLProfile.audio:
        ydl_opts[
            "format"
        ] = "bestaudio[ext=opus]/bestaudio[ext=webm]/bestaudio[ext=ogg]/bestaudio[ext=oga]/bestaudio/best"
        ydl_opts["postprocessors"].append({"key": "FFmpegExtractAudio", "preferredcodec": args.ext})

    match_filters = ["live_status=?not_live"]
    if args.small:
        match_filters.append("duration >? 59 & duration <? 14399")
    match_filter_user_config = ydl_opts.get("match_filter")
    if match_filter_user_config is not None:
        match_filters.append(match_filter_user_config)
    ydl_opts["match_filter"] = yt_dlp.utils.match_filter_func(" & ".join(match_filters).split(" | "))

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(m["path"], download=True)
        except yt_dlp.DownloadError as e:
            error = utils.REGEX_ANSI_ESCAPE.sub("", str(e))
            log.warning("[%s]: yt-dlp %s", m["path"], error)
            update_media(args, m["path"], error=error)
            return
        if info is None:
            log.warning("[%s]: yt-dlp returned no info", m["path"])
            update_media(args, m["path"], error="yt-dlp returned no info")
            return

        if m["profile"] == DLProfile.audio:
            info["local_path"] = ydl.prepare_filename({**info, "ext": args.ext})
        else:
            info["local_path"] = ydl.prepare_filename(info)

        ydl_errors = ydl_log["error"] + ydl_log["warning"]
        ydl_errors = "\n".join([s for s in ydl_errors if not yt_meaningless_errors.match(s)])

        if not ydl_log["error"]:
            log.debug("[%s]: No news is good news", m["path"])
            update_media(args, m["path"], info, m["profile"])
        elif yt_recoverable_errors.match(ydl_errors):
            log.info("[%s]: Recoverable error matched. %s", m["path"], ydl_errors)
            update_media(args, m["path"], info, error=ydl_errors)
        elif yt_unrecoverable_errors.match(ydl_errors):
            log.info("[%s]: Unrecoverable error matched. %s", m["path"], ydl_errors)
            update_media(args, m["path"], info, error=ydl_errors, URE=True)
        else:
            log.warning("[%s]: Unknown error. %s", m["path"], ydl_errors)


def dl_download(args=None) -> None:
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

    Print download queue groups

        library playlists dl.db -p g
        TODO: update image
    """,
    )
    media = process_downloadqueue(args)
    for m in media:
        # check again in case it was already completed by another process
        path = list(args.db.query("select path from media where path=?", [m["path"]]))
        if not path:
            log.info("[%s]: Already downloaded. Skipping!", m["path"])
            continue

        if m.get("profile") is None:
            m["profile"] = DLProfile.video

        if m["profile"] in (DLProfile.audio, DLProfile.video):
            yt(args, m)
        # elif m['profile'] == DLProfile.image:
        else:
            raise NotImplementedError

    db.optimize(args)
