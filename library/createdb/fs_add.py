import argparse, json, math, os, sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from pathlib import Path
from shutil import which

from library import usage
from library.createdb.fs_add_metadata import extract_image_metadata_chunk, extract_metadata
from library.createdb.subtitle import clean_up_temp_dirs
from library.mediadb import db_media, db_playlists, playlists
from library.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    file_utils,
    iterables,
    objects,
    printing,
)
from library.utils.consts import SC, DBType
from library.utils.log_utils import log


def parse_args(action, usage):
    parser = argparse_utils.ArgumentParser(usage=usage)
    arggroups.db_profiles(parser)

    parser.add_argument("--exclude", "-E", nargs="+", action="extend", default=[])

    arggroups.media_scan(parser)
    parser.add_argument("--process", action="store_true")

    arggroups.clobber(parser)
    arggroups.process_ffmpeg(parser)

    parser.add_argument("--check-corrupt", "--check-corruption", action="store_true")
    arggroups.media_check(parser)
    parser.set_defaults(gap="10%")

    parser.add_argument(
        "--force", "-f", action="store_true", help="Mark all subpath files as deleted if no files found"
    )
    parser.add_argument("--clean-path", action=argparse.BooleanOptionalAction, default=True, help="Clean output path")
    parser.add_argument("--copy")
    parser.add_argument("--move")

    arggroups.debug(parser)

    arggroups.database(parser)
    if action == SC.fs_add:
        arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=action == SC.fs_add)

    if not args.profiles:
        args.profiles = [DBType.video]

    if args.copy:
        args.copy = Path(args.copy).expanduser().resolve()
    if args.move:
        args.move = Path(args.move).expanduser().resolve()

    if hasattr(args, "paths"):
        args.paths = iterables.conform(args.paths)

    if not which("ffprobe") and (DBType.audio in args.profiles or DBType.video in args.profiles):
        log.error("ffmpeg is not installed. Install it with your package manager.")
        raise SystemExit(3)

    arggroups.process_ffmpeg_post(args)

    return args


def extract_chunk(args, media) -> None:
    if objects.is_profile(args, DBType.image):
        media = extract_image_metadata_chunk(media)

    if args.scan_subtitles:
        clean_up_temp_dirs()

    captions = []
    for d in media:
        caption = {}
        caption["path"] = d["path"]

        caption["chapters"] = d.pop("chapters", None) or []
        caption["subtitles"] = d.pop("subtitles", None) or []

        tags = d.pop("tags", None) or ""
        description = d.pop("description", None) or ""
        if description:
            tags += "\n" + description
        if tags:
            caption["captions_t0"] = {"time": 0, "text": tags}

        captions.append(caption)

    media = iterables.list_dict_filter_bool(media)
    media = [{"playlists_id": args.playlists_id, **d} for d in media]
    args.db["media"].insert_all(media, pk=["playlists_id", "path"], alter=True, replace=True)

    for d in captions:
        media_id = args.db.pop("select id from media where path = ?", [d["path"]])
        if len(d["chapters"]) > 0:
            args.db["captions"].insert_all([{**d, "media_id": media_id} for d in d["chapters"]], alter=True)
        if len(d["subtitles"]) > 0:
            args.db["captions"].insert_all([{**d, "media_id": media_id} for d in d["subtitles"]], alter=True)
        if d.get("caption_t0"):
            args.db["captions"].insert({**d["caption_t0"], "media_id": media_id}, alter=True)


def find_new_files(args, path) -> list[str]:
    if path.is_file():
        path = str(path)
        if db_media.exists(args, path):
            try:
                time_deleted = args.db.pop(
                    """select time_deleted from media where path = ?""",
                    [path],
                )
            except Exception as e:
                log.debug(e)
            else:
                if time_deleted > 0:
                    undeleted_count = db_media.mark_media_undeleted(args, [path])
                    if undeleted_count > 0:
                        print(f"[{path}] Marking as undeleted")
        return [path]

    for s in args.profiles:
        if getattr(DBType, s, None) is None:
            msg = f"fs_extract for profile {s}"
            raise NotImplementedError(msg)

    exts = args.ext
    if not exts:
        if args.scan_all_files or DBType.filesystem in args.profiles:
            exts = None
        else:
            exts = set()
            if DBType.audio in args.profiles:
                exts |= consts.AUDIO_ONLY_EXTENSIONS
            if DBType.video in args.profiles:
                exts |= consts.VIDEO_EXTENSIONS
            if DBType.image in args.profiles:
                exts |= consts.IMAGE_EXTENSIONS
            if DBType.text in args.profiles:
                exts |= consts.TEXTRACT_EXTENSIONS
            if args.ocr:
                exts |= consts.OCR_EXTENSIONS
            if args.speech_recognition:
                exts |= consts.SPEECH_RECOGNITION_EXTENSIONS
            exts = tuple(exts)

    scanned_set = file_utils.rglob(path, exts or None, args.exclude)[0]

    m_columns = db_utils.columns(args, "media")

    try:
        deleted_set = {
            d["path"]
            for d in args.db.query(
                f"""select path from media
                where 1=1
                    and time_deleted > 0
                    and path like ?
                    {'AND time_downloaded > 0' if 'time_downloaded' in m_columns else ''}
                """,
                [str(path) + os.sep + "%"],
            )
        }
    except Exception as e:
        log.debug(e)
    else:
        undeleted_files = list(deleted_set.intersection(scanned_set))
        undeleted_count = db_media.mark_media_undeleted(args, undeleted_files)
        if undeleted_count > 0:
            print(f"[{path}] Marking", undeleted_count, "metadata records as undeleted")

    try:
        existing_set = {
            d["path"]
            for d in args.db.query(
                f"""select path from media
                where 1=1
                    and path like ?
                    and coalesce(time_deleted, 0) = 0
                    {'AND time_downloaded > 0' if 'time_downloaded' in m_columns else ''}
                """,
                [str(path) + os.sep + "%"],
            )
        }
    except Exception as e:
        log.debug(e)
        new_files = list(scanned_set)
    else:
        new_files = list(scanned_set - existing_set)

        deleted_files = list(existing_set - scanned_set)
        if not scanned_set and len(deleted_files) >= len(existing_set) and not args.force:
            print(f"[{path}] Path empty or device not mounted. Rerun with -f to mark all subpaths as deleted.")
            return []  # if path not mounted or all files deleted
        deleted_count = db_media.mark_media_deleted(args, deleted_files)
        if deleted_count > 0:
            print(f"[{path}] Marking", deleted_count, "orphaned metadata records as deleted")

    new_files.sort(key=len, reverse=True)
    return new_files


def scan_path(args, path_str: str) -> int:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        print(f"[{path}] Path does not exist")
        if args.force:
            playlists.delete_playlists(args, [str(path)])
        return 0

    n_jobs = None
    if args.verbose >= consts.LOG_DEBUG:
        n_jobs = 1
    elif args.threads != -1:
        n_jobs = args.threads

    threadsafe = [DBType.audio, DBType.video, DBType.filesystem]

    if path.is_dir():
        info = {
            "extractor_key": "Local",
            "extractor_config": args.extractor_config,
            "time_deleted": 0,
        }
        args.playlists_id = db_playlists.add(args, str(path), info, check_subpath=True)
    else:
        args.playlists_id = 0

    print(f"[{path}] Building file list...")
    new_files = find_new_files(args, path)
    if new_files:
        print(f"[{path}] Adding {len(new_files)} new media")
        # log.debug(new_files)

        if getattr(args, "process", False) and n_jobs:
            batch_count = n_jobs
        elif DBType.text in args.profiles:
            batch_count = int(os.cpu_count() or 4)
        elif DBType.image in args.profiles:
            batch_count = consts.SQLITE_PARAM_LIMIT // 20
        else:
            batch_count = consts.SQLITE_PARAM_LIMIT // 100
        chunks_count = math.ceil(len(new_files) / batch_count)
        files_chunked = iterables.chunks(new_files, batch_count)

        if all(s in threadsafe for s in args.profiles):
            pool_fn = ThreadPoolExecutor
        else:
            pool_fn = ProcessPoolExecutor

        start_time = consts.now()
        with pool_fn(n_jobs) as parallel:
            for idx, chunk_paths in enumerate(files_chunked):
                percent = (idx + 1) / chunks_count * 100
                eta = printing.eta(idx + 1, chunks_count, start_time=start_time) if chunks_count > 2 else ""
                printing.print_overwrite(
                    f"[{path}] Extracting metadata chunk {idx + 1} of {chunks_count} ({percent:3.1f}%) {eta}"
                )

                mp_args = argparse.Namespace(
                    playlist_path=path, **{k: v for k, v in args.__dict__.items() if k not in {"db"}}
                )
                metadata = parallel.map(partial(extract_metadata, mp_args), chunk_paths)
                metadata = list(filter(None, metadata))
                extract_chunk(args, metadata)
            print()

    return len(new_files)


def extractor(args, paths) -> None:
    new_files = 0
    for path in paths:
        new_files += scan_path(args, path)

    log.info("Imported %s paths", new_files)

    if not args.db["media"].detect_fts() or new_files > 100000:
        db_utils.optimize(args)


def fs_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(SC.fs_add, usage.fs_add)

    db_playlists.create(args)
    db_media.create(args)

    extractor(args, args.paths)


def fs_update(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(SC.fs_update, usage.fs_update)

    fs_playlists = list(
        args.db.query(
            f"""
            SELECT *
            FROM playlists
            WHERE extractor_key = 'Local'
            ORDER BY
                length(path)-length(REPLACE(path, '{os.sep}', '')) desc
                , path
            """,
        ),
    )

    for playlist in fs_playlists:
        extractor_config = json.loads(playlist.get("extractor_config") or "{}")
        args_env = arg_utils.override_config(args, extractor_config)

        extractor(args_env, [playlist["path"]])
