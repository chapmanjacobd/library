import argparse, math, os, sys
from pathlib import Path

from joblib import Parallel, delayed

from xklb import av, books, db, paths, subtitle, utils
from xklb.player import mark_media_deleted
from xklb.utils import SQLITE_PARAM_LIMIT, log


def calculate_sparseness(stat):
    if stat.st_size == 0:
        sparseness = 0
    else:
        blocks_allocated = stat.st_blocks * 512
        sparseness = blocks_allocated / stat.st_size
    return sparseness


def extract_metadata(args, f):
    log.debug(f)

    try:
        stat = os.stat(f)
    except Exception:
        return

    media = dict(
        path=f,
        size=stat.st_size,
        time_created=int(stat.st_ctime),
        time_modified=int(stat.st_mtime),
    )

    if hasattr(stat, "st_blocks"):
        media = {**media, "sparseness": calculate_sparseness(stat)}

    if args.db_type == "f":
        media = {**media, "is_dir": os.path.isdir(f)}

    if args.db_type == "t":
        return books.munge_book_tags(media, f)

    if args.db_type in ["a", "v"]:
        return av.munge_av_tags(args, media, f)

    return media


def extract_chunk(args, l):
    n_jobs = -1
    if args.db_type in ["t", "p"]:
        n_jobs = (os.cpu_count() or 4) * 5
    if args.verbose > 0:
        n_jobs = 1
    metadata = Parallel(n_jobs=n_jobs, backend="threading")(delayed(extract_metadata)(args, file) for file in l) or []

    if args.db_type == "i":
        metadata = books.extract_image_metadata_chunk(metadata, l)

    [p.unlink() for p in Path(paths.SUB_TEMP_DIR).glob("*.srt")]

    args.db["media"].insert_all(list(filter(None, metadata)), pk="path", alter=True, replace=True)


def find_new_files(args, path):
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
            [d["path"] for d in args.db.query(f"select path from media where is_deleted=0 and path like '{path}%'")]
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


def scan_path(args, path):
    path = Path(path).resolve()
    if not path.exists():
        return 0
    print(f"[{path}] Building file list...")

    new_files = find_new_files(args, path)

    if len(new_files) > 0:
        print(f"[{path}] Adding {len(new_files)} new media")
        log.debug(new_files)

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


def extractor(args):
    Path(args.database).touch()
    args.db = db.connect(args)
    new_files = 0
    for path in args.paths:
        new_files += scan_path(args, path)

    if new_files > 0 or args.optimize:
        db.optimize(args)


def parse_args():
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


def main(args=None):
    if args:
        sys.argv[1:] = args

    args = parse_args()

    extractor(args)


if __name__ == "__main__":
    main()
