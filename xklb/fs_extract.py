import argparse, math, os, sys
from multiprocessing import TimeoutError as mp_TimeoutError
from pathlib import Path
from timeit import default_timer as timer
from typing import Dict, List, Optional

from joblib import Parallel, delayed

from xklb import av, books, consts, db, utils
from xklb.consts import SC, DBType
from xklb.player import mark_media_deleted
from xklb.utils import log


def calculate_sparseness(stat) -> int:
    if stat.st_size == 0:
        sparseness = 0
    else:
        blocks_allocated = stat.st_blocks * 512
        sparseness = blocks_allocated / stat.st_size
    return sparseness


def extract_metadata(mp_args, f) -> Optional[Dict[str, int]]:
    log.debug(f)

    try:
        stat = os.stat(f)
    except Exception:
        log.error(f"[{f}] Could not read file stats (possible filesystem corruption; check dmesg)")
        return

    media = {
        "path": f,
        "play_count": 0,
        "time_played": 0,
        "size": stat.st_size,
        "time_created": int(stat.st_ctime),
        "time_modified": int(stat.st_mtime),
        "time_downloaded": consts.NOW,
        "time_deleted": 0,
        "ie_key": "Local",
    }

    if hasattr(stat, "st_blocks"):
        media = {**media, "sparseness": calculate_sparseness(stat)}

    if mp_args.profile == DBType.filesystem:
        media = {**media, "is_dir": os.path.isdir(f)}

    if mp_args.profile in (DBType.audio, DBType.video):
        return av.munge_av_tags(mp_args, media, f)

    if mp_args.profile == DBType.text:
        try:
            start = timer()
            if any([mp_args.ocr, mp_args.speech_recognition]):
                media = books.munge_book_tags_slow(media, f)
            else:
                media = books.munge_book_tags_fast(media, f)
        except mp_TimeoutError:
            log.warning(f"[{f}]: Timed out trying to read file")
            return media
        else:
            log.debug(f"[{f}]: {timer()-start}")
            return media

    return media


def extract_chunk(args, chunk_paths) -> None:
    n_jobs = -1
    if args.profile in (DBType.text, DBType.image, DBType.filesystem):
        n_jobs = consts.CPU_COUNT
    if args.verbose >= 2:
        n_jobs = 1

    mp_args = argparse.Namespace(**{k: v for k, v in args.__dict__.items() if k not in {"db"}})
    metadata = Parallel(n_jobs=n_jobs)(delayed(extract_metadata)(mp_args, p) for p in chunk_paths) or []

    if args.profile == DBType.image:
        metadata = books.extract_image_metadata_chunk(metadata, chunk_paths)

    if args.scan_subtitles:
        for p in Path(consts.SUB_TEMP_DIR).glob("*.srt"):
            p.unlink()

    media = list(filter(None, metadata))
    args.db["media"].insert_all(utils.list_dict_filter_bool(media), pk="path", alter=True, replace=True)


def find_new_files(args, path: Path) -> List[str]:
    if args.profile == DBType.audio:
        scanned_files = consts.get_media_files(path, audio=True)
    elif args.profile == DBType.video:
        scanned_files = consts.get_media_files(path)
    elif args.profile == DBType.text:
        scanned_files = consts.get_text_files(path, OCR=args.ocr, speech_recognition=args.speech_recognition)
    elif args.profile == DBType.image:
        scanned_files = consts.get_image_files(path)
    elif args.profile == DBType.filesystem:
        # thanks to these people for making rglob fast https://bugs.python.org/issue26032
        scanned_files = [str(p) for p in path.rglob("*")]
    else:
        raise Exception(f"fs_extract for profile {args.profile} not implemented")

    columns = args.db["media"].columns_dict
    scanned_set = set(scanned_files)

    try:
        existing_set = set(
            [
                d["path"]
                for d in args.db.query(
                    f"""select path from media
                where 1=1
                    and time_deleted=0
                    and path like '{path}%'
                    {'AND time_downloaded > 0' if 'time_downloaded' in columns else ''}
                """
                )
            ]
        )
    except Exception as e:
        log.debug(e)
        new_files = list(scanned_set)
    else:
        new_files = list(scanned_set - existing_set)

        deleted_files = list(existing_set - scanned_set)
        if not new_files and len(deleted_files) >= len(existing_set) and not args.force:
            return []  # if path not mounted or all files deleted
        deleted_count = mark_media_deleted(args, deleted_files)
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
        "category": category,
        **args.extra_playlist_data,
    }
    args.db["playlists"].upsert(utils.dict_filter_bool(playlist), pk="path", alter=True)


def scan_path(args, path_str: str) -> int:
    path = Path(path_str).resolve()
    if not path.exists():
        print(f"[{path}] Path does not exist")
        if not args.force:
            return 0
    print(f"[{path}] Building file list...")

    new_files = find_new_files(args, path)

    if new_files:
        print(f"[{path}] Adding {len(new_files)} new media")
        log.debug(new_files)

        if args.profile in (DBType.text):
            batch_count = consts.CPU_COUNT
        else:
            batch_count = consts.SQLITE_PARAM_LIMIT // 100
        chunks_count = math.ceil(len(new_files) / batch_count)
        df_chunked = utils.chunks(new_files, batch_count)
        for idx, l in enumerate(df_chunked):
            percent = ((batch_count * idx) + len(l)) / len(new_files) * 100
            print(f"[{path}] Extracting metadata {percent:3.1f}% (chunk {idx + 1} of {chunks_count})")
            extract_chunk(args, l)

    _add_folder(args, path)

    return len(new_files)


def parse_args(action, usage) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library " + action, usage=usage)

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--audio", "-A", action="store_const", dest="profile", const=DBType.audio, help="Create audio database"
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
        "--video", "-V", action="store_const", dest="profile", const=DBType.video, help="Create video database"
    )
    profile.add_argument(
        "--text", "-T", action="store_const", dest="profile", const=DBType.text, help="Create text database"
    )
    profile.add_argument(
        "--image", "-I", action="store_const", dest="profile", const=DBType.image, help="Create image database"
    )
    parser.set_defaults(profile=DBType.video)
    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)

    parser.add_argument("--ocr", "--OCR", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--speech-recognition", "--speech", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scan-subtitles", "--scan-subtitle", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--extra-media-data", default={})
    parser.add_argument("--extra-playlist-data", default={})

    parser.add_argument("--delete-unplayable", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force", "-f", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database", nargs="?")
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
            raise Exception(f"fs_extract for profile {args.profile} not implemented")

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db.connect(args)
    if hasattr(args, "paths"):
        args.paths = utils.conform(args.paths)
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def extractor(args, paths) -> None:
    new_files = 0
    for path in paths:
        new_files += scan_path(args, path)

    if not args.db["media"].detect_fts() or new_files > 100000:
        db.optimize(args)


def fs_add(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        SC.fsadd,
        """library fsadd [--audio | --video | --image |  --text | --filesystem] -c CATEGORY [database] paths ...

    The default database type is video:
        library fsadd ./tv/
        library fsadd --video ./tv/  # equivalent

    This will create audio.db in the current directory:
        library fsadd --audio ./music/

    This will create image.db in the current directory:
        library fsadd --image ./photos/

    This will create text.db in the current directory:
        library fsadd --text ./documents_and_books/

    Create text database and scan with OCR and speech-recognition:
        library fsadd --text --ocr --speech-recognition ./receipts_and_messages/

    Create video database and read internal/external subtitle files for use in search:
        library fsadd --scan-subtitles ./tv/

    The database location must be specified to reference more than one path:
        library fsadd --audio podcasts.db ./podcasts/ ./another/folder/
    """,
    )

    extractor(args, args.paths)


def fs_update(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args(
        SC.fsupdate,
        """library fsupdate database

    Update each path previously saved:

        library fsupdate database
    """,
    )

    playlists = list(
        args.db.query(
            """
            SELECT *
            FROM playlists
            WHERE ie_key = 'Local'
            ORDER BY
                length(path)-length(REPLACE(path, '/', '')) desc
                , path
            """
        )
    )

    for playlist in playlists:
        args_env = args if playlist["config"] is None else argparse.Namespace(**{**playlist["config"], **args.__dict__})
        extractor(args_env, [playlist["path"]])
