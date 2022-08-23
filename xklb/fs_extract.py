import argparse
import math
import os
import sys
from pathlib import Path
from shutil import which
from sqlite3 import OperationalError
from typing import Dict

import ffmpeg
import mutagen
import pandas as pd
from joblib import Parallel, delayed
from tinytag import TinyTag

from xklb.db import fetchall_dict, sqlite_con
from xklb.subtitle import get_subtitle, has_external_subtitle, youtube_dl_id
from xklb.utils import (
    SQLITE_PARAM_LIMIT,
    chunks,
    cmd,
    combine,
    filter_None,
    get_media_files,
    log,
    safe_unpack,
    single_column_tolist,
)
from xklb.utils_player import mark_media_deleted


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
            print(f"Failed reading {f}", file=sys.stderr)
            if args.delete_unplayable:
                if which("trash-put") is not None:
                    cmd("trash-put", f, strict=False)
                else:
                    Path(f).unlink()
            return

        if not "format" in probe:
            print(f"Failed reading format {f}", file=sys.stderr)
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
        width = safe_unpack([s.get("width") for s in streams if s.get("tags") is not None])
        height = safe_unpack([s.get("height") for s in streams if s.get("tags") is not None])
        codec_types = [s.get("codec_type") for s in streams]
        tags = [s.get("tags") for s in streams if s.get("tags") is not None]
        language = combine([t.get("language") for t in tags if t.get("language") not in [None, "und", "unk"]])

        video_count = sum([1 for s in codec_types if s == "video"])
        audio_count = sum([1 for s in codec_types if s == "audio"])
        attachment_count = sum([1 for s in codec_types if s == "attachment"])
        subtitle_count = sum([1 for s in codec_types if s == "subtitle"])
        chapter_count = len(probe["chapters"])

        if subtitle_count == 0 and args.db_type == "v":
            try:
                has_sub = has_external_subtitle(f)
            except Exception:
                has_sub = False
            if has_sub:
                subtitle_count = 1

        media = {
            **media,
            "is_deleted": 0,
            "play_count": 0,
            "time_played": 0,
            "video_count": video_count,
            "audio_count": audio_count,
            "subtitle_count": subtitle_count,
            "chapter_count": chapter_count,
            "attachment_count": attachment_count,
            "width": width,
            "height": height,
            "fps": fps,
            "language": language,
            "provenance": get_provenance(f),
            "duration": 0 if not duration else int(float(duration)),
        }

    if args.db_type == "a":
        try:
            tiny_tags = filter_None(TinyTag.get(f).as_dict())
        except Exception:
            tiny_tags = dict()

        try:
            mutagen_tags = filter_None(mutagen.File(f).tags.as_dict())
        except Exception:
            mutagen_tags = dict()

        tags = parse_tags(mutagen_tags, tiny_tags)
        return {**media, **tags}

    return media


def get_columns(args):
    try:
        query = "SELECT name FROM PRAGMA_TABLE_INFO('media') where type in ('TEXT', 'INTEGER');"
        cols = single_column_tolist(args.con.execute(query).fetchall(), "name")
    except OperationalError:
        cols = []
    return cols


def optimize_db(args):
    print("Optimizing database")
    if Path(args.database).exists():
        cmd("sqlite-utils", "optimize", args.database)
        columns = get_columns(args)

        for column in columns:
            cmd("sqlite-utils", "create-index", "--if-not-exists", "--analyze", args.database, "media", column)


def extract_chunk(args, l):
    metadata = (
        Parallel(n_jobs=-1 if args.verbose == 0 else 1, backend="threading")(
            delayed(extract_metadata)(args, file) for file in l
        )
        or []
    )

    DF = pd.DataFrame(list(filter(None, metadata)))

    DF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
        "media",
        con=args.con,
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
            single_column_tolist(
                fetchall_dict(args.con, f"select path from media where is_deleted=0 and path like '{path}%'"), "path"
            )
        )
    except Exception:
        scanned_files = list(new_files)
    else:
        scanned_files = list(new_files - existing)

        deleted_files = list(existing - new_files)
        deleted_count = mark_media_deleted(args, deleted_files)
        if deleted_count > 0:
            print("Marking", deleted_count, "orphaned metadata records as deleted")

    return scanned_files


def scan_path(args, path):
    path = Path(path).resolve()
    print(f"{path} : Scanning...")

    new_files = find_new_files(args, path)

    if len(new_files) > 0:
        print(f"Adding {len(new_files)} new media")
        log.debug(new_files)

        batch_count = SQLITE_PARAM_LIMIT // 100
        chunks_count = math.ceil(len(new_files) / batch_count)
        df_chunked = chunks(new_files, batch_count)
        for idx, l in enumerate(df_chunked):
            percent = ((batch_count * idx) + len(l)) / len(new_files) * 100
            print(f"[{path}] Extracting metadata {percent:3.1f}% (chunk {idx + 1} of {chunks_count})")
            extract_chunk(args, l)

            if args.subtitle:
                print("Fetching subtitles")
                Parallel(n_jobs=5)(delayed(get_subtitle)(args, file) for file in l)

    return len(new_files)


def extractor(args):
    Path(args.database).touch()
    args.con = sqlite_con(args.database)
    new_files = 0
    for path in args.paths:
        new_files += scan_path(args, path)

    if new_files > 0:
        optimize_db(args)


def parse_args():
    parser = argparse.ArgumentParser(prog="lb extract")
    parser.add_argument("database", nargs="?")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--db", "-db")

    db_type = parser.add_mutually_exclusive_group()
    db_type.add_argument("-a", "--audio", action="store_const", dest="db_type", const="a")
    db_type.add_argument("-fs", "--filesystem", action="store_const", dest="db_type", const="f")
    db_type.add_argument("--video", action="store_const", dest="db_type", const="v")
    parser.set_defaults(db_type="v")

    parser.add_argument("-s", "--subtitle", action="store_true")
    parser.add_argument("-yt", "--youtube-only", action="store_true")
    parser.add_argument("-sl", "--subliminal-only", action="store_true")
    parser.add_argument("-d", "--delete-unplayable", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
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
    return args


def main(args=None):
    if args:
        sys.argv[1:] = args

    args = parse_args()

    extractor(args)


if __name__ == "__main__":
    main()
