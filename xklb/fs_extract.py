import argparse, math, os, sys
from multiprocessing import TimeoutError
from pathlib import Path
from timeit import default_timer as timer
from typing import Dict, List, Union

from joblib import Parallel, delayed

from xklb import av, books, db, paths, subtitle, utils
from xklb.player import mark_media_deleted
from xklb.utils import SQLITE_PARAM_LIMIT, log


def calculate_sparseness(stat) -> int:
    if stat.st_size == 0:
        sparseness = 0
    else:
        blocks_allocated = stat.st_blocks * 512
        sparseness = blocks_allocated / stat.st_size
    return sparseness


def extract_metadata(mp_args, f) -> Union[Dict[str, int], None]:
    log.debug(f)

    try:
        stat = os.stat(f)
    except Exception:
        log.error(f"[{f}] Could not read file stats (possible filesystem corruption; check dmesg)")
        return

    media = dict(
        path=f,
        size=stat.st_size,
        time_created=int(stat.st_ctime),
        time_modified=int(stat.st_mtime),
        is_deleted=0,
        play_count=0,
        time_played=0,
    )

    if hasattr(stat, "st_blocks"):
        media = {**media, "sparseness": calculate_sparseness(stat)}

    if mp_args.db_type == "f":
        media = {**media, "is_dir": os.path.isdir(f)}

    if mp_args.db_type in ["a", "v"]:
        return av.munge_av_tags(mp_args, media, f)

    if mp_args.db_type == "t":
        try:
            start = timer()
            if any([mp_args.ocr, mp_args.speech_recognition]):
                media = books.munge_book_tags_slow(media, f)
            else:
                media = books.munge_book_tags_fast(media, f)
        except TimeoutError:
            log.warning(f"[{f}]: Timed out trying to read file")
            return media
        else:
            log.debug(f"[{f}]: {timer()-start}")
            return media

    return media


def extract_chunk(args, chunk_paths) -> None:
    n_jobs = -1
    if args.db_type in ["t", "p", "f"]:
        n_jobs = utils.CPU_COUNT
    if args.verbose >= 2:
        n_jobs = 1

    mp_args = argparse.Namespace(**{k: v for k, v in args.__dict__.items() if k not in {"db"}})
    metadata = Parallel(n_jobs=n_jobs)(delayed(extract_metadata)(mp_args, p) for p in chunk_paths) or []

    if args.db_type == "i":
        metadata = books.extract_image_metadata_chunk(metadata, chunk_paths)

    if args.scan_subtitles:
        [p.unlink() for p in Path(paths.SUB_TEMP_DIR).glob("*.srt")]

    args.db["media"].insert_all(list(filter(None, metadata)), pk="path", alter=True, replace=True)


def find_new_files(args, path) -> List[str]:
    if args.db_type == "a":
        scanned_files = paths.get_media_files(path, audio=True)
    elif args.db_type == "v":
        scanned_files = paths.get_media_files(path)
    elif args.db_type == "t":
        scanned_files = paths.get_text_files(path, OCR=args.ocr, speech_recognition=args.speech_recognition)
    elif args.db_type == "i":
        scanned_files = paths.get_image_files(path)
    elif args.db_type == "f":
        # thanks to these people for making rglob fast https://bugs.python.org/issue26032
        scanned_files = [str(p) for p in Path(path).resolve().rglob("*")]
    else:
        raise Exception(f"fs_extract for db_type {args.db_type} not implemented")

    scanned_set = set(scanned_files)

    try:
        existing_set = set(
            [
                d["path"]
                for d in args.db.query(
                    f"""select path from media
                where 1=1
                    and is_deleted=0
                    and path like '{path}%'
                    {'AND is_downloaded=1' if 'is_downloaded' in args.db['media'].columns else ''}
                """
                )
            ]
        )
    except Exception:
        new_files = list(scanned_set)
    else:
        new_files = list(scanned_set - existing_set)

        deleted_files = list(existing_set - scanned_set)
        if len(new_files) == 0 and len(deleted_files) >= len(existing_set):
            return []  # if path not mounted or all files deleted
        deleted_count = mark_media_deleted(args, deleted_files)
        if deleted_count > 0:
            print(f"[{path}] Marking", deleted_count, "orphaned metadata records as deleted")

    return new_files


def scan_path(args, path) -> int:
    path = Path(path).resolve()
    if not path.exists():
        print(f"[{path}] Path does not exist")
        return 0
    print(f"[{path}] Building file list...")

    new_files = find_new_files(args, path)

    if len(new_files) > 0:
        print(f"[{path}] Adding {len(new_files)} new media")
        log.debug(new_files)

        if args.db_type in ["t"]:
            batch_count = utils.CPU_COUNT
        else:
            batch_count = SQLITE_PARAM_LIMIT // 100
        chunks_count = math.ceil(len(new_files) / batch_count)
        df_chunked = utils.chunks(new_files, batch_count)
        for idx, l in enumerate(df_chunked):
            percent = ((batch_count * idx) + len(l)) / len(new_files) * 100
            print(f"[{path}] Extracting metadata {percent:3.1f}% (chunk {idx + 1} of {chunks_count})")
            extract_chunk(args, l)

            if args.subtitle:
                print(f"[{path}] Fetching subtitles")
                Parallel(n_jobs=5)(delayed(subtitle.get)(args, file) for file in l)

    return len(new_files)


def extractor(args) -> None:
    Path(args.database).touch()
    args.db = db.connect(args)
    new_files = 0
    for path in args.paths:
        new_files += scan_path(args, path)

    if new_files > 0 or args.optimize:
        db.optimize(args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library fsadd",
        usage="""library fsadd [--audio | --video | --image |  --text | --filesystem] [database] paths ...

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

    Run with --optimize to add indexes to every int and text column:
        library fsadd --optimize --audio ./music/

    The database location must be specified to reference more than one path:
        library fsadd --audio podcasts.db ./podcasts/ ./another/folder/
""",
    )
    parser.add_argument("database", nargs="?")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    db_type = parser.add_mutually_exclusive_group()
    db_type.add_argument("--audio", action="store_const", dest="db_type", const="a", help="Create audio database")
    db_type.add_argument(
        "--filesystem", action="store_const", dest="db_type", const="f", help="Create filesystem database"
    )
    db_type.add_argument("--video", action="store_const", dest="db_type", const="v", help="Create video database")
    db_type.add_argument("--text", action="store_const", dest="db_type", const="t", help="Create text database")
    db_type.add_argument("--image", action="store_const", dest="db_type", const="i", help="Create image database")
    parser.set_defaults(db_type="v")

    parser.add_argument("--ocr", "--OCR", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--speech-recognition", "--speech", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scan-subtitles", "--scan-subtitle", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--subtitle", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--youtube-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--subliminal-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--delete-unplayable", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--optimize", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    if args.db:
        args.database = args.db

    if not args.database:
        if args.db_type == "a":
            args.database = "audio.db"
        elif args.db_type == "f":
            args.database = "fs.db"
        elif args.db_type == "v":
            args.database = "video.db"
        elif args.db_type == "t":
            args.database = "text.db"
        elif args.db_type == "i":
            args.database = "image.db"
        else:
            raise Exception(f"fs_extract for db_type {args.db_type} not implemented")

    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def main(args=None) -> None:
    if args:
        sys.argv[1:] = args

    args = parse_args()

    extractor(args)


if __name__ == "__main__":
    main()
