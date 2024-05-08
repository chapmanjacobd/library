import argparse, json, math, os, re, sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from multiprocessing import TimeoutError as mp_TimeoutError
from pathlib import Path
from shutil import which
from timeit import default_timer as timer

from xklb import usage
from xklb.createdb import av
from xklb.files import sample_hash
from xklb.folders import rel_mv
from xklb.mediadb import db_media, db_playlists, playlists
from xklb.mediafiles import process_ffmpeg, process_image
from xklb.utils import (
    arg_utils,
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    file_utils,
    iterables,
    nums,
    objects,
    path_utils,
    processes,
    strings,
)
from xklb.utils.consts import SC, DBType
from xklb.utils.log_utils import log

REGEX_SENTENCE_ENDS = re.compile(r";|,|\.|\*|\n|\t")


def parse_args(action, usage):
    parser = argparse_utils.ArgumentParser(prog="library " + action, usage=usage)
    arggroups.db_profiles(parser)
    arggroups.simulate(parser)

    parser.add_argument(
        "--io-multiplier",
        type=float,
        default=1.0,
        help="Especially useful for text, image, filesystem db types",
    )
    parser.add_argument("--ocr", "--OCR", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--speech-recognition", "--speech", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scan-subtitles", "--scan-subtitle", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--hash", action="store_true")
    parser.add_argument("--move")

    parser.add_argument("--process", action="store_true", help=argparse.SUPPRESS)
    arggroups.process_ffmpeg(parser)

    parser.add_argument("--check-corrupt", "--check-corruption", action="store_true")
    arggroups.media_check(parser)
    parser.set_defaults(gap="0.10")

    parser.add_argument(
        "--force", "-f", action="store_true", help="Mark all subpath files as deleted if no files found"
    )
    arggroups.debug(parser)

    arggroups.database(parser)
    if action == SC.fs_add:
        parser.add_argument("paths", nargs="+")
    args = parser.parse_intermixed_args()

    if not args.profiles:
        args.profiles = [DBType.video]

    if args.move:
        args.move = Path(args.move).expanduser().resolve()

    if hasattr(args, "paths"):
        args.paths = iterables.conform(args.paths)

    if not which("ffprobe") and (DBType.audio in args.profiles or DBType.video in args.profiles):
        log.error("ffmpeg is not installed. Install it with your package manager.")
        raise SystemExit(3)

    arggroups.process_ffmpeg_post(args)
    arggroups.media_check_post(args)

    arggroups.args_post(args, parser, create_db=action == SC.fs_add)
    return args


def munge_book_tags(path) -> dict:
    try:
        import textract  # type: ignore
    except ModuleNotFoundError:
        print(
            "textract is required for text database creation: pip install textract; sudo dnf install libxml2-devel libxslt-devel antiword unrtf poppler-utils tesseract sox-plugins-nonfree sox libjpeg-devel swig",
        )
        raise
    try:
        tags = textract.process(path, language=os.getenv("TESSERACT_LANGUAGE"))
        tags = REGEX_SENTENCE_ENDS.split(tags.decode())
    except Exception as e:
        log.warning(e)
        log.error(f"Failed reading text. {path}")
        tags = []
    return {"tags": strings.combine(tags)}


munge_book_tags_fast = processes.with_timeout(70)(munge_book_tags)
munge_book_tags_slow = processes.with_timeout(350)(munge_book_tags)


def extract_metadata(mp_args, path) -> dict[str, str | int | None] | None:
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

    ext = path.rsplit(".", 1)[-1].lower()
    is_scan_all_files = getattr(mp_args, "scan_all_files", False)

    if media["type"] == "directory":
        return None

    if media["size"] == 0 or not Path(path).exists():
        return media

    if objects.is_profile(mp_args, DBType.audio) and (ext in consts.AUDIO_ONLY_EXTENSIONS or is_scan_all_files):
        media |= av.munge_av_tags(mp_args, path)
    elif objects.is_profile(mp_args, DBType.video) and (ext in consts.VIDEO_EXTENSIONS or is_scan_all_files):
        media |= av.munge_av_tags(mp_args, path)

    if not Path(path).exists():  # av.munge_av_tags might delete if unplayable or corruption exceeds threshold
        return media

    text_exts = consts.TEXTRACT_EXTENSIONS
    if mp_args.ocr:
        text_exts |= consts.OCR_EXTENSIONS
    if mp_args.speech_recognition:
        text_exts |= consts.SPEECH_RECOGNITION_EXTENSIONS
    if objects.is_profile(mp_args, DBType.text) and (ext in text_exts or is_scan_all_files):
        try:
            start = timer()
            if any([mp_args.ocr, mp_args.speech_recognition]):
                media |= munge_book_tags_slow(path)
            else:
                media |= munge_book_tags_fast(path)
        except mp_TimeoutError:
            log.warning(f"Timed out trying to read file. {path}")
        else:
            log.debug(f"{timer()-start} {path}")

    if getattr(mp_args, "hash", False) and media["type"] != "directory" and media["size"] > 0:
        media["hash"] = sample_hash.sample_hash_file(path)

    if getattr(mp_args, "move", False) and not file_utils.is_file_open(path):
        dest_path = rel_mv.gen_rel_path(path, mp_args.move)
        dest_path = path_utils.clean_path(bytes(dest_path))
        file_utils.rename_move_file(path, dest_path, simulate=mp_args.simulate)
        path = media["path"] = dest_path

    if getattr(mp_args, "process", False):
        if objects.is_profile(mp_args, DBType.audio) and Path(path).suffix not in [".opus", ".mka"]:
            result = process_ffmpeg.process_path(
                mp_args,
                path,
                split_longer_than=2160 if mp_args.split_longer_than is None and "audiobook" in path.lower() else None,
            )
            if result is None:
                return None
            path = media["path"] = str(result)
        elif objects.is_profile(mp_args, DBType.video) and Path(path).suffix not in [".av1.mkv"]:
            result = process_ffmpeg.process_path(mp_args, path)
            if result is None:
                return None
            path = media["path"] = str(result)
        elif objects.is_profile(mp_args, DBType.image) and Path(path).suffix not in [".avif", ".avifs"]:
            result = process_image.process_path(mp_args, path)
            if result is None:
                return None
            path = media["path"] = str(result)

    return media


def clean_up_temp_dirs():
    temp_subs_path = Path(consts.SUB_TEMP_DIR)
    if temp_subs_path.exists():
        for p in temp_subs_path.glob("*.srt"):
            p.unlink()


def pop_substring_keys(e, key_substring):
    values = []
    for k in list(e.keys()):
        if key_substring in k:
            values.append(e.pop(k))
    return values


def munge_image_tags(m: dict, e: dict) -> dict:
    chroma_subsample = nums.safe_int(
        iterables.safe_unpack(
            e.pop("File:YCbCrSubSampling", None),
            *pop_substring_keys(e, "YCbCrSubSampling"),
        )
    )
    if chroma_subsample == 0:
        chroma_subsample = None

    unit_x = iterables.safe_unpack(
        *pop_substring_keys(e, "XResolution"),
    )
    unit_y = iterables.safe_unpack(
        *pop_substring_keys(e, "YResolution"),
    )
    unit = iterables.safe_unpack(
        *pop_substring_keys(e, "ResolutionUnit"),
    )
    if unit == 0:
        unit = None
        unit_x = None if unit_x == 1 else unit_x
        unit_y = None if unit_y == 1 else unit_y

    m = {
        **m,
        "orientation": iterables.safe_unpack(
            *pop_substring_keys(e, "Orientation"),
        ),
        "width": iterables.safe_unpack(
            e.pop("File:ImageWidth", None),
            e.pop("Composite:ImageWidth", None),
            e.pop("EXIF:ImageWidth", None),
            e.pop("EXIF:ExifImageWidth", None),
            e.pop("PNG:ImageWidth", None),
            *pop_substring_keys(e, "ImageWidth"),
        ),
        "height": iterables.safe_unpack(
            e.pop("File:ImageHeight", None),
            e.pop("Composite:ImageHeight", None),
            e.pop("EXIF:ImageHeight", None),
            e.pop("EXIF:ExifImageHeight", None),
            e.pop("PNG:ImageHeight", None),
            *pop_substring_keys(e, "ImageHeight"),
        ),
        "chroma_subsample": chroma_subsample,
        "color_depth": iterables.safe_unpack(
            *pop_substring_keys(e, "ColorResolutionDepth"),
        ),
        "color_background": iterables.safe_unpack(
            *pop_substring_keys(e, "BackgroundColor"),
        ),
        "color_transparent": iterables.safe_unpack(
            *pop_substring_keys(e, "TransparentColor"),
        ),
        "longitude": iterables.safe_unpack(
            e.pop("Composite:GPSLongitude", None),
            *pop_substring_keys(e, "GPSLongitude"),
        ),
        "latitude": iterables.safe_unpack(
            e.pop("Composite:GPSLatitude", None),
            *pop_substring_keys(e, "GPSLatitude"),
        ),
        "focal_length": iterables.safe_unpack(
            e.pop("Composite:Lens", None),
            *pop_substring_keys(e, "Lens35efl"),
        ),
        "unit": unit,
        "unit_x": unit_x,
        "unit_y": unit_y,
        "exiftool_warning": strings.combine(*pop_substring_keys(e, "ExifTool:Warning")),
        "tags": strings.combine(
            *pop_substring_keys(e, "Headline"),
            *pop_substring_keys(e, "Title"),
            *pop_substring_keys(e, "ImageDescription"),
            *pop_substring_keys(e, "Caption"),
            *pop_substring_keys(e, "Artist"),
            *pop_substring_keys(e, "By-line"),
            *pop_substring_keys(e, "Credit"),
            *pop_substring_keys(e, "DocumentNotes"),
            *pop_substring_keys(e, "URL_List"),
            *pop_substring_keys(e, "Keywords"),
            *pop_substring_keys(e, "Make"),
            *pop_substring_keys(e, "Model"),
            *pop_substring_keys(e, "LensID"),
            *pop_substring_keys(e, "Creator"),
            *pop_substring_keys(e, "Software"),
        ),
    }

    return m


def extract_image_metadata_chunk(metadata: list[dict]) -> list[dict]:
    try:
        import exiftool
    except ModuleNotFoundError:
        print(
            "exiftool and PyExifTool are required for image database creation: sudo dnf install perl-Image-ExifTool && pip install PyExifTool",
        )
        raise

    chunk_paths = [d["path"] for d in metadata]
    try:
        with exiftool.ExifToolHelper() as et:
            exif = et.get_metadata(chunk_paths)
    except exiftool.exceptions.ExifToolExecuteError:
        log.exception("exifTool failed executing get_metadata %s", metadata)
        return metadata

    exif_enriched = []
    for m, e in zip(metadata, exif):
        assert m["path"] == e.pop("SourceFile")

        try:
            m = munge_image_tags(m, e)
        except Exception as e:
            log.error("[%s]: %s", m["path"], e)
            # continue ?
        exif_enriched.append(m)

    return exif_enriched


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


def find_new_files(args, path) -> list[str]:
    if path.is_file():
        scanned_set = {str(path)}
    else:
        for s in args.profiles:
            if getattr(DBType, s, None) is None:
                msg = f"fs_extract for profile {s}"
                raise NotImplementedError(msg)

        exts = args.ext
        if not exts:
            exts = set()
            if args.scan_all_files or DBType.filesystem in args.profiles:
                exts = None
            else:
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

        if DBType.filesystem in args.profiles:
            scanned_set = set.union(*file_utils.rglob(path))
        else:
            scanned_set = file_utils.rglob(path, exts)[0]

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
    elif args.io_multiplier != 1.0:
        n_jobs = max(1, int(max(os.cpu_count() or 4, 4) * args.io_multiplier))

    threadsafe = [DBType.audio, DBType.video, DBType.filesystem]

    info = {
        "extractor_key": "Local",
        "extractor_config": args.extractor_config,
        "time_deleted": 0,
    }
    args.playlists_id = db_playlists.add(args, str(path), info, check_subpath=True)

    print(f"[{path}] Building file list...")
    new_files = find_new_files(args, path)
    if new_files:
        print(f"[{path}] Adding {len(new_files)} new media")
        # log.debug(new_files)

        if DBType.text in args.profiles:
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

    if not args.db["media"].detect_fts() or new_files > 100000:
        db_utils.optimize(args)


def fs_add(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args(SC.fs_add, usage.fs_add)
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
