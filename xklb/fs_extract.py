import argparse, math, os, sys
from pathlib import Path
from shutil import which
from typing import Dict

import ffmpeg
import mutagen
import pandas as pd
from joblib import Parallel, delayed
from tinytag import TinyTag

from xklb import db, subtitle, utils
from xklb.paths import SUB_TEMP_DIR, get_media_files, youtube_dl_id
from xklb.player import mark_media_deleted
from xklb.utils import SQLITE_PARAM_LIMIT, cmd, combine, log, safe_unpack


def get_provenance(file):
    if youtube_dl_id(file) != "":
        return "YouTube"

    return None


def parse_tags(mutagen: Dict, tinytag: Dict):
    tags = {
        "mood": combine(
            mutagen.get("albummood"),
            mutagen.get("MusicMatch_Situation"),
            mutagen.get("Songs-DB_Occasion"),
            mutagen.get("albumgrouping"),
        ),
        "genre": combine(mutagen.get("genre"), tinytag.get("genre"), mutagen.get("albumgenre")),
        "year": combine(
            mutagen.get("originalyear"),
            mutagen.get("TDOR"),
            mutagen.get("TORY"),
            mutagen.get("date"),
            mutagen.get("TDRC"),
            mutagen.get("TDRL"),
            tinytag.get("year"),
        ),
        "bpm": safe_unpack(mutagen.get("fBPM"), mutagen.get("bpm_accuracy")),
        "key": safe_unpack(mutagen.get("TIT1"), mutagen.get("key_accuracy"), mutagen.get("TKEY")),
        "time": combine(mutagen.get("time_signature")),
        "decade": safe_unpack(mutagen.get("Songs-DB_Custom1")),
        "categories": safe_unpack(mutagen.get("Songs-DB_Custom2")),
        "city": safe_unpack(mutagen.get("Songs-DB_Custom3")),
        "country": combine(
            mutagen.get("Songs-DB_Custom4"),
            mutagen.get("MusicBrainz Album Release Country"),
            mutagen.get("musicbrainz album release country"),
            mutagen.get("language"),
        ),
        "description": combine(
            mutagen.get("description"),
            mutagen.get("lyrics"),
            tinytag.get("comment"),
        ),
        "album": safe_unpack(tinytag.get("album"), mutagen.get("album")),
        "title": safe_unpack(tinytag.get("title"), mutagen.get("title")),
        "artist": combine(
            tinytag.get("artist"),
            mutagen.get("artist"),
            mutagen.get("artists"),
            tinytag.get("albumartist"),
            tinytag.get("composer"),
        ),
    }

    # print(mutagen)
    # breakpoint()

    return tags


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

    if args.db_type in ["a", "v"]:
        try:
            probe = ffmpeg.probe(f, show_chapters=None)
        except (KeyboardInterrupt, SystemExit):
            exit(130)
        except Exception:
            print(f"[{f}] Failed reading header", file=sys.stderr)
            if args.delete_unplayable:
                if which("trash-put") is not None:
                    cmd("trash-put", f, strict=False)
                else:
                    Path(f).unlink()
            return

        if not "format" in probe:
            print(f"[{f}] Failed reading format", file=sys.stderr)
            print(probe)
            return

        format = probe["format"]
        format.pop("size", None)
        format.pop("tags", None)
        format.pop("bit_rate", None)
        format.pop("format_name", None)
        format.pop("format_long_name", None)
        format.pop("nb_programs", None)
        format.pop("nb_streams", None)
        format.pop("probe_score", None)
        format.pop("start_time", None)
        format.pop("filename", None)
        duration = format.pop("duration", None)

        if format != {}:
            log.info("Extra data %s", format)
            # breakpoint()

        streams = probe["streams"]

        def parse_framerate(string):
            top, bot = string.split("/")
            bot = int(bot)
            if bot == 0:
                return None
            return int(int(top) / bot)

        fps = safe_unpack(
            [
                parse_framerate(s.get("avg_frame_rate"))
                for s in streams
                if s.get("avg_frame_rate") is not None and "/0" not in s.get("avg_frame_rate")
            ]
            + [
                parse_framerate(s.get("r_frame_rate"))
                for s in streams
                if s.get("r_frame_rate") is not None and "/0" not in s.get("r_frame_rate")
            ]
        )
        width = safe_unpack([s.get("width") for s in streams])
        height = safe_unpack([s.get("height") for s in streams])
        codec_types = [s.get("codec_type") for s in streams]
        stream_tags = [s.get("tags") for s in streams if s.get("tags") is not None]
        language = combine([t.get("language") for t in stream_tags if t.get("language") not in [None, "und", "unk"]])

        video_count = sum([1 for s in codec_types if s == "video"])
        audio_count = sum([1 for s in codec_types if s == "audio"])
        chapter_count = len(probe["chapters"])

        media = {
            **media,
            "is_deleted": 0,
            "play_count": 0,
            "time_played": 0,
            "video_count": video_count,
            "audio_count": audio_count,
            "chapter_count": chapter_count,
            "width": width,
            "height": height,
            "fps": fps,
            "duration": 0 if not duration else int(float(duration)),
            "language": language,
            "provenance": get_provenance(f),
        }

        if args.db_type == "v":
            attachment_count = sum([1 for s in codec_types if s == "attachment"])
            internal_subtitles = utils.conform(
                [
                    subtitle.extract(f, s["index"])
                    for s in streams
                    if s.get("codec_type") == "subtitle" and s.get("codec_name") not in subtitle.IMAGE_SUBTITLE_CODECS
                ],
            )

            external_subtitles = subtitle.get_external(f)
            subs_text = subtitle.subs_to_text(f, internal_subtitles + external_subtitles)

            video_tags = {
                "subtitle_count": len(internal_subtitles + external_subtitles),
                "attachment_count": attachment_count,
                "tags": combine(subs_text),
            }
            return {**media, **video_tags}

        if args.db_type == "a":
            try:
                tiny_tags = utils.dict_filter_bool(TinyTag.get(f).as_dict())
            except Exception:
                tiny_tags = dict()

            try:
                mutagen_tags = utils.dict_filter_bool(mutagen.File(f).tags.as_dict())
            except Exception:
                mutagen_tags = dict()

            stream_tags = parse_tags(mutagen_tags, tiny_tags)
            return {**media, **stream_tags}

    return media


def extract_chunk(args, l):
    metadata = (
        Parallel(n_jobs=-1 if args.verbose == 0 else 1, backend="threading")(
            delayed(extract_metadata)(args, file) for file in l
        )
        or []
    )

    [p.unlink() for p in Path(SUB_TEMP_DIR).glob("*.srt")]

    DF = pd.DataFrame(list(filter(None, metadata)))

    DF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
        "media",
        con=args.db.conn,
        if_exists="append",
        index=False,
        chunksize=70,
        method="multi",
    )


def find_new_files(args, path):
    if args.db_type == "a":
        scanned_files = get_media_files(path, audio=True)
    elif args.db_type == "v":
        scanned_files = get_media_files(path)
    elif args.db_type == "f":
        # thanks to these people for making rglob fast https://bugs.python.org/issue26032
        scanned_files = [str(p) for p in Path(path).resolve().rglob("*")]
    else:
        raise Exception(f"fs_extract for db_type {args.db_type} not implemented")

    new_files = set(scanned_files)

    try:
        existing = set(
            [d["path"] for d in args.db.query(f"select path from media where is_deleted=0 and path like '{path}%'")]
        )
    except Exception:
        scanned_files = list(new_files)
    else:
        scanned_files = list(new_files - existing)

        deleted_files = list(existing - new_files)
        deleted_count = mark_media_deleted(args, deleted_files)
        if deleted_count > 0:
            print(f"[{path}] Marking", deleted_count, "orphaned metadata records as deleted")

    return scanned_files


def scan_path(args, path):
    path = Path(path).resolve()
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
        prog="lb fsadd",
        usage="""lb fsadd [--audio | --video | --filesystem] [database] paths ...

    The default database type is video:
        lb fsadd ./tv/
        lb fsadd --video ./tv/  # equivalent

    This will create audio.db in the current directory:
        lb fsadd --audio ./music/

    Run with --optimize to add indexes to every int and text column:
        lb fsadd --optimize --audio ./music/

    The database location must be specified to reference more than one path:
        lb fsadd --audio podcasts.db ./podcasts/ ./another/folder/
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
    parser.set_defaults(db_type="v")

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
