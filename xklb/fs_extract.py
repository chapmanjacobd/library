import argparse, json, math, os, sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from multiprocessing import TimeoutError as mp_TimeoutError
from pathlib import Path
from shutil import which
from timeit import default_timer as timer
from typing import Dict, List, Optional

from xklb import db_media, db_playlists, usage
from xklb.media import av, books
from xklb.scripts import playlists, process_audio, sample_hash
from xklb.utils import arg_utils, consts, db_utils, file_utils, iterables, nums, objects, path_utils
from xklb.utils.consts import SC, DBType
from xklb.utils.log_utils import log


def parse_args(action, usage):
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
        "--fs",
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
    parser.add_argument("--ext", action=arg_utils.ArgparseList)

    parser.add_argument(
        "--io-multiplier",
        type=float,
        default=1.0,
        help="Especially useful for text, image, filesystem db types",
    )
    parser.add_argument("--ocr", "--OCR", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--speech-recognition", "--speech", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scan-subtitles", "--scan-subtitle", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--delete-unplayable", action="store_true")
    parser.add_argument("--hash", action="store_true")
    parser.add_argument("--process", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--move")

    parser.add_argument("--check-corrupt", "--check-corruption", action="store_true")
    parser.add_argument(
        "--chunk-size",
        type=float,
        help="Duration to decode per segment (default 0.5 second). If set, recommended to use >0.1 seconds",
        default=0.5,
    )
    parser.add_argument(
        "--gap",
        default="0.1",
        help="Width between chunks to skip (default 10%%). Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument(
        "--delete-corrupt",
        "--delete-corruption",
        help="delete media that is more corrupt or equal to this threshold. Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument(
        "--full-scan-if-corrupt",
        "--full-scan-if-corruption",
        help="full scan as second pass if initial scan result more corruption or equal to this threshold. Values greater than 1 are treated as number of seconds",
    )
    parser.add_argument("--full-scan", action="store_true")

    parser.add_argument("--force", "-f", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    if action == SC.fsadd:
        parser.add_argument("paths", nargs="+")
    args = parser.parse_intermixed_args()

    if args.move:
        args.move = str(Path(args.move).expanduser().resolve())

    args.gap = nums.float_from_percent(args.gap)
    if args.delete_corrupt:
        args.delete_corrupt = nums.float_from_percent(args.delete_corrupt)
    if args.full_scan_if_corrupt:
        args.full_scan_if_corrupt = nums.float_from_percent(args.full_scan_if_corrupt)

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db_utils.connect(args)

    if hasattr(args, "paths"):
        args.paths = iterables.conform(args.paths)
    log.info(objects.dict_filter_bool(args.__dict__))

    if args.profile in (DBType.audio, DBType.video) and not which("ffprobe"):
        log.error("ffmpeg is not installed. Install it with your package manager.")
        raise SystemExit(3)

    return args, parser


def extract_metadata(mp_args, path) -> Optional[Dict[str, int]]:
    try:
        path.encode()
    except UnicodeEncodeError:
        log.error("Could not encode file path as UTF-8. Skipping %s", path)
        return None

    try:
        stat = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        log.error(f"IOError: possible filesystem corruption; check dmesg. {path}")
        return None
    except Exception as e:
        log.error(f"%s {path}", e)
        return None

    media = {
        "path": path,
        "size": stat.st_size,
        "type": file_utils.mimetype(path),
        "time_created": int(stat.st_ctime),
        "time_modified": int(stat.st_mtime) or consts.now(),
        "time_downloaded": consts.APPLICATION_START,
        "time_deleted": 0,
    }

    if mp_args.profile in (DBType.audio, DBType.video):
        media |= av.munge_av_tags(mp_args, path)

    if not Path(path).exists():
        return media

    if mp_args.profile == DBType.text:
        try:
            start = timer()
            if any([mp_args.ocr, mp_args.speech_recognition]):
                media |= books.munge_book_tags_slow(path)
            else:
                media |= books.munge_book_tags_fast(path)
        except mp_TimeoutError:
            log.warning(f"Timed out trying to read file. {path}")
        else:
            log.debug(f"{timer()-start} {path}")

    if getattr(mp_args, "hash", False):
        # TODO: it would be better if this was saved to and checked against an external global file
        media["hash"] = sample_hash.sample_hash_file(path)

    if getattr(mp_args, "process", False):
        if mp_args.profile == DBType.audio and Path(path).suffix not in [".opus", ".mka"]:
            path = media["path"] = process_audio.process_path(
                path, split_longer_than="36mins" if "audiobook" in path.lower() else None
            )

    if getattr(mp_args, "move", False) and not file_utils.is_file_open(path):
        dest_path = bytes(Path(mp_args.move) / Path(path).relative_to(mp_args.playlist_path))
        dest_path = path_utils.clean_path(dest_path)
        file_utils.rename_move_file(path, dest_path)
        media["path"] = dest_path

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

    media = [{"playlist_id": args.playlist_id, **d} for d in media]
    media = iterables.list_dict_filter_bool(media)
    args.db["media"].insert_all(media, pk="id", alter=True, replace=True)

    for d in captions:
        media_id = args.db.pop("select id from media where path = ?", [d["path"]])
        if len(d["chapters"]) > 0:
            args.db["captions"].insert_all([{**d, "media_id": media_id} for d in d["chapters"]], alter=True)
        if len(d["subtitles"]) > 0:
            args.db["captions"].insert_all([{**d, "media_id": media_id} for d in d["subtitles"]], alter=True)
        if d.get("caption_t0"):
            args.db["captions"].insert({**d["caption_t0"], "media_id": media_id}, alter=True)


def mark_media_undeleted(args, paths) -> int:
    paths = iterables.conform(paths)

    modified_row_count = 0
    if paths:
        df_chunked = iterables.chunks(paths, consts.SQLITE_PARAM_LIMIT)
        for chunk_paths in df_chunked:
            with args.db.conn:
                cursor = args.db.conn.execute(
                    """update media
                    set time_deleted=0
                    where path in ("""
                    + ",".join(["?"] * len(chunk_paths))
                    + ")",
                    (*chunk_paths,),
                )
                modified_row_count += cursor.rowcount

    return modified_row_count


def find_new_files(args, path) -> List[str]:
    if path.is_file():
        scanned_set = set([str(path)])
    else:
        if args.ext:
            scanned_set = file_utils.rglob(path, args.ext)[0]
        elif args.scan_all_files:
            scanned_set = file_utils.rglob(path)[0]
        elif args.profile == DBType.filesystem:
            scanned_set = set.union(*file_utils.rglob(path))
        elif args.profile == DBType.audio:
            scanned_set = file_utils.get_audio_files(path)
        elif args.profile == DBType.video:
            scanned_set = file_utils.get_video_files(path)
        elif args.profile == DBType.text:
            scanned_set = file_utils.get_text_files(
                path,
                image_recognition=args.ocr,
                speech_recognition=args.speech_recognition,
            )
        elif args.profile == DBType.image:
            scanned_set = file_utils.get_image_files(path)
        else:
            msg = f"fs_extract for profile {args.profile}"
            raise NotImplementedError(msg)

    m_columns = db_utils.columns(args, "media")

    try:
        deleted_set = {
            d["path"]
            for d in args.db.query(
                f"""select path from media
                where 1=1
                    and time_deleted > 0
                    and path like '{path}%'
                    {'AND time_downloaded > 0' if 'time_downloaded' in m_columns else ''}
                """,
            )
        }
    except Exception as e:
        log.debug(e)
    else:
        undeleted_files = list(deleted_set.intersection(scanned_set))
        undeleted_count = mark_media_undeleted(args, undeleted_files)
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
                [str(path) + "%"],
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
    elif args.io_multiplier != 1.0:
        n_jobs = max(1, int(max(os.cpu_count() or 4, 4) * args.io_multiplier))

    threadsafe = [DBType.audio, DBType.video, DBType.filesystem]

    info = {
        "extractor_key": "Local",
        "extractor_config": objects.dict_filter_bool(
            {k: v for k, v in args.__dict__.items() if k not in ["db", "database", "verbose", "force", "paths"]}
        ),
        "time_deleted": 0,
    }
    args.playlist_id = db_playlists.add(args, str(path), info, check_subpath=True)

    print(f"[{path}] Building file list...")
    new_files = find_new_files(args, path)
    if new_files:
        print(f"[{path}] Adding {len(new_files)} new media")
        # log.debug(new_files)

        if args.profile in (DBType.text):
            batch_count = int(os.cpu_count() or 4)
        elif args.profile in (DBType.image):
            batch_count = consts.SQLITE_PARAM_LIMIT // 20
        else:
            batch_count = consts.SQLITE_PARAM_LIMIT // 100
        chunks_count = math.ceil(len(new_files) / batch_count)
        files_chunked = iterables.chunks(new_files, batch_count)

        if args.profile in threadsafe:
            pool_fn = ThreadPoolExecutor
        else:
            pool_fn = ProcessPoolExecutor

        with pool_fn(n_jobs) as parallel:
            for idx, chunk_paths in enumerate(files_chunked):
                percent = ((batch_count * idx) + len(chunk_paths)) / len(new_files) * 100
                print(f"[{path}] Extracting metadata {percent:3.1f}% (chunk {idx + 1} of {chunks_count})")

                mp_args = argparse.Namespace(
                    playlist_path=path, **{k: v for k, v in args.__dict__.items() if k not in {"db"}}
                )
                metadata = parallel.map(partial(extract_metadata, mp_args), chunk_paths)
                metadata = list(filter(None, metadata))
                extract_chunk(args, metadata)

    return len(new_files)


def extractor(args, paths) -> None:
    new_files = 0
    for path in paths:
        new_files += scan_path(args, path)

    log.info("Imported %s paths", new_files)

    if args.profile in [DBType.audio, DBType.video, DBType.text] and (
        not args.db["media"].detect_fts() or new_files > 100000
    ):
        db_utils.optimize(args)


def fs_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args, _parser = parse_args(SC.fsadd, usage.fsadd)

    extractor(args, args.paths)


def fs_update(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args, parser = parse_args(SC.fsupdate, usage.fsupdate)

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
        args_env = arg_utils.override_config(parser, extractor_config, args)

        extractor(args_env, [playlist["path"]])
