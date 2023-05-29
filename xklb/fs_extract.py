import argparse, math, os, sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from copy import deepcopy
from functools import partial
from multiprocessing import TimeoutError as mp_TimeoutError
from pathlib import Path
from shutil import which
from timeit import default_timer as timer
from typing import Dict, List, Optional

from xklb import av, books, consts, db, player, usage, utils
from xklb.consts import SC, DBType
from xklb.utils import log


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library " + action, usage=usage)

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--audio",
        "-A",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Create audio database",
    )
    profile.add_argument(
        "--filesystem",
        "-F",
        action="store_const",
        dest="profile",
        const=DBType.filesystem,
        help="Create filesystem database",
    )
    profile.add_argument(
        "--video",
        "-V",
        action="store_const",
        dest="profile",
        const=DBType.video,
        help="Create video database",
    )
    profile.add_argument(
        "--text",
        "-T",
        action="store_const",
        dest="profile",
        const=DBType.text,
        help="Create text database",
    )
    profile.add_argument(
        "--image",
        "-I",
        action="store_const",
        dest="profile",
        const=DBType.image,
        help="Create image database",
    )
    parser.set_defaults(profile=DBType.video)
    parser.add_argument("--scan-all-files", "-a", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)

    parser.add_argument(
        "--io-multiplier",
        type=float,
        default=1.0,
        help="Especially useful for text, image, filesystem db types",
    )
    parser.add_argument("--ocr", "--OCR", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--speech-recognition", "--speech", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scan-subtitles", "--scan-subtitle", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--extra-media-data", default={})
    parser.add_argument("--extra-playlist-data", default={})

    parser.add_argument("--delete-unplayable", action="store_true")
    parser.add_argument(
        "--check-corrupt",
        type=float,
        default=0.0,
        help="check that 0 to 100 percent of media decodes correctly",
    )
    parser.add_argument("--delete-corrupt", type=float, help="delete media that is more corrupt than this threshold")
    parser.add_argument("--force", "-f", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    if action == SC.fsadd:
        parser.add_argument("paths", nargs="+")
    args = parser.parse_args()

    if args.db:
        args.database = args.db

    if not args.database:
        if args.profile == DBType.audio:
            args.database = "audio.db"
        elif args.profile == DBType.filesystem:
            args.database = "fs.db"
        elif args.profile == DBType.video:
            args.database = "video.db"
        elif args.profile == DBType.text:
            args.database = "text.db"
        elif args.profile == DBType.image:
            args.database = "image.db"
        else:
            msg = f"fs_extract for profile {args.profile}"
            raise NotImplementedError(msg)

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)
    if hasattr(args, "paths"):
        args.paths = utils.conform(args.paths)
    log.info(utils.dict_filter_bool(args.__dict__))

    if args.profile in (DBType.audio, DBType.video) and not which("ffprobe"):
        log.error("ffmpeg is not installed. Install it with your package manager.")
        raise SystemExit(3)

    return args


def calculate_sparseness(stat) -> int:
    if stat.st_size == 0:
        sparseness = 0
    else:
        blocks_allocated = stat.st_blocks * 512
        sparseness = blocks_allocated / stat.st_size
    return sparseness


def extract_metadata(mp_args, path) -> Optional[Dict[str, int]]:
    log.debug(path)

    try:
        stat = Path(path).stat()
    except FileNotFoundError:
        return None
    except OSError:
        log.error(f"[{path}] IOError: possible filesystem corruption; check dmesg")
        return None
    except Exception as e:
        log.error(f"[{path}] %s", e)
        return None

    media = {
        "path": path,
        "play_count": 0,
        "time_played": 0,
        "playhead": 0,
        "size": stat.st_size,
        "time_created": int(stat.st_ctime),
        "time_modified": int(stat.st_mtime) or consts.now(),
        "time_downloaded": consts.APPLICATION_START,
        "time_deleted": 0,
        "ie_key": "Local",
    }

    if hasattr(stat, "st_blocks"):
        media = {**media, "sparseness": calculate_sparseness(stat)}

    if mp_args.profile == DBType.filesystem:
        media = {**media, "is_dir": Path(path).is_dir()}

    if mp_args.profile in (DBType.audio, DBType.video):
        media = av.munge_av_tags(mp_args, media, path)

    if mp_args.profile == DBType.text:
        try:
            start = timer()
            if any([mp_args.ocr, mp_args.speech_recognition]):
                media = books.munge_book_tags_slow(media, path)
            else:
                media = books.munge_book_tags_fast(media, path)
        except mp_TimeoutError:
            log.warning(f"[{path}]: Timed out trying to read file")
        else:
            log.debug(f"[{path}]: {timer()-start}")

    return media


def clean_up_temp_dirs():
    temp_subs_path = Path(consts.SUB_TEMP_DIR)
    if temp_subs_path.exists():
        for p in temp_subs_path.glob("*.srt"):
            p.unlink()


def extract_chunk(args, media) -> None:
    if args.profile == DBType.image:
        media = books.extract_image_metadata_chunk(media)

    if args.scan_subtitles:
        clean_up_temp_dirs()

    captions_t0 = []
    for d in media:
        chapters = d.pop("chapters", None) or []
        if len(chapters) > 0:
            args.db["captions"].insert_all(chapters, alter=True)

        subtitles = d.pop("subtitles", None) or []
        if len(subtitles) > 0:
            args.db["captions"].insert_all(subtitles, alter=True)

        tags = d.pop("tags", None) or ""
        description = d.pop("description", None) or ""
        if description:
            tags += "\n" + description
        if tags:
            captions_t0.append({"path": d["path"], "time": 0, "text": tags})
    args.db["captions"].insert_all(captions_t0, alter=True)

    media = utils.list_dict_filter_bool(media)
    args.db["media"].insert_all(utils.list_dict_filter_bool(media), pk="path", alter=True, replace=True)


def find_new_files(args, path: Path) -> List[str]:
    if path.is_file():
        scanned_files = [str(path)]
    else:
        try:
            if args.scan_all_files:
                # thanks to these people for making rglob fast https://bugs.python.org/issue26032
                scanned_files = [str(p) for p in path.rglob("*") if p.is_file()]
            elif args.profile == DBType.filesystem:
                scanned_files = [str(p) for p in path.rglob("*")]
            elif args.profile == DBType.audio:
                scanned_files = consts.get_audio_files(path)
            elif args.profile == DBType.video:
                scanned_files = consts.get_video_files(path)
            elif args.profile == DBType.text:
                scanned_files = consts.get_text_files(
                    path,
                    image_recognition=args.ocr,
                    speech_recognition=args.speech_recognition,
                )
            elif args.profile == DBType.image:
                scanned_files = consts.get_image_files(path)
            else:
                msg = f"fs_extract for profile {args.profile}"
                raise NotImplementedError(msg)
        except FileNotFoundError:
            print(f"[{path}] Not found")
            return []

    columns = args.db["media"].columns_dict
    scanned_set = set(scanned_files)

    try:
        deleted_set = {
            d["path"]
            for d in args.db.query(
                f"""select path from media
                where 1=1
                    and time_deleted > 0
                    and path like '{path}%'
                    {'AND time_downloaded > 0' if 'time_downloaded' in columns else ''}
                """,
            )
        }
    except Exception as e:
        log.debug(e)
    else:
        undeleted_files = list(deleted_set.intersection(scanned_set))
        undeleted_count = player.mark_media_undeleted(args, undeleted_files)
        if undeleted_count > 0:
            print(f"[{path}] Marking", undeleted_count, "metadata records as undeleted")

    try:
        existing_set = {
            d["path"]
            for d in args.db.query(
                f"""select path from media
                where 1=1
                    and time_deleted = 0
                    and path like '{path}%'
                    {'AND time_downloaded > 0' if 'time_downloaded' in columns else ''}
                """,
            )
        }
    except Exception as e:
        log.debug(e)
        new_files = list(scanned_set)
    else:
        new_files = list(scanned_set - existing_set)

        deleted_files = list(existing_set - scanned_set)
        if not new_files and len(deleted_files) >= len(existing_set) and not args.force:
            print(f"[{path}] Path empty or device not mounted. Rerun with -f to mark all subpaths as deleted.")
            return []  # if path not mounted or all files deleted
        deleted_count = player.mark_media_deleted(args, deleted_files)
        if deleted_count > 0:
            print(f"[{path}] Marking", deleted_count, "orphaned metadata records as deleted")

    return new_files


def _add_folder(args, folder_path: Path) -> None:
    category = args.category or folder_path.parts[-1]

    playlist = {
        "ie_key": "Local",
        "path": str(folder_path),
        "config": utils.filter_namespace(args, ["ocr", "speech_recognition", "scan_subtitles"]),
        "time_deleted": 0,
        "profile": args.profile,
        "category": category,
        **args.extra_playlist_data,
    }
    args.db["playlists"].upsert(utils.dict_filter_bool(playlist), pk="path", alter=True)


def scan_path(args, path_str: str) -> int:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        print(f"[{path}] Path does not exist")
        if args.force:
            player.delete_playlists(args, [str(path)])
        return 0

    n_jobs = None
    if args.check_corrupt > 0:
        n_jobs = int(min(os.cpu_count() or 2, 2) * args.io_multiplier)
    if args.io_multiplier > 1:
        n_jobs = int(max(os.cpu_count() or 4, 4) * args.io_multiplier)
    if args.verbose >= consts.LOG_DEBUG:
        n_jobs = 1

    threadsafe = [DBType.audio, DBType.video, DBType.filesystem]

    print(f"[{path}] Building file list...")
    new_files = find_new_files(args, path)
    if new_files:
        print(f"[{path}] Adding {len(new_files)} new media")
        log.debug(new_files)

        if args.profile in (DBType.text):
            batch_count = int(os.cpu_count() or 4)
        elif args.profile in (DBType.image):
            batch_count = consts.SQLITE_PARAM_LIMIT // 20
        else:
            batch_count = consts.SQLITE_PARAM_LIMIT // 100
        chunks_count = math.ceil(len(new_files) / batch_count)
        df_chunked = utils.chunks(new_files, batch_count)

        if args.profile in threadsafe:
            pool_fn = ThreadPoolExecutor
        else:
            pool_fn = ProcessPoolExecutor

        with pool_fn(n_jobs) as parallel:
            for idx, chunk_paths in enumerate(df_chunked):
                percent = ((batch_count * idx) + len(chunk_paths)) / len(new_files) * 100
                print(f"[{path}] Extracting metadata {percent:3.1f}% (chunk {idx + 1} of {chunks_count})")

                mp_args = argparse.Namespace(**{k: v for k, v in args.__dict__.items() if k not in {"db"}})
                metadata = parallel.map(partial(extract_metadata, mp_args), chunk_paths)
                metadata = list(filter(None, metadata))
                extract_chunk(args, metadata)

    _add_folder(args, path)

    return len(new_files)


def extractor(args, paths) -> None:
    new_files = 0
    for path in paths:
        new_files += scan_path(args, path)

    log.info("Imported %s paths", new_files)

    if args.profile in [DBType.audio, DBType.video, DBType.text] and (
        not args.db["media"].detect_fts() or new_files > 100000
    ):
        db.optimize(args)


def fs_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(SC.fsadd, usage.fsadd)

    extractor(args, args.paths)


def fs_update(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(SC.fsupdate, usage.fsupdate)

    playlists = list(
        args.db.query(
            """
            SELECT *
            FROM playlists
            WHERE ie_key = 'Local'
            ORDER BY
                length(path)-length(REPLACE(path, '/', '')) desc
                , path
            """,
        ),
    )

    for playlist in playlists:
        args_env = argparse.Namespace(
            **{**(playlist.get("config") or {}), **args.__dict__, "profile": playlist["profile"]},
        )

        extractor(args_env, [playlist["path"]])
