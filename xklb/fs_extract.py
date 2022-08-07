import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict

import mutagen
import pandas as pd
from joblib import Parallel, delayed
from tinytag import TinyTag

from xklb.db import fetchall_dict, sqlite_con
from xklb.subtitle import get_subtitle, is_file_with_subtitle, youtube_dl_id
from xklb.utils import (
    SQLITE_PARAM_LIMIT,
    chunks,
    cmd,
    combine,
    filter_None,
    get_media_files,
    log,
    remove_media,
    safe_unpack,
)

audio_include_string = (
    lambda x: f"""and (
    path like :include{x}
    OR mood like :include{x}
    OR genre like :include{x}
    OR year like :include{x}
    OR bpm like :include{x}
    OR key like :include{x}
    OR time like :include{x}
    OR decade like :include{x}
    OR categories like :include{x}
    OR city like :include{x}
    OR country like :include{x}
    OR description like :include{x}
    OR album like :include{x}
    OR title like :include{x}
    OR artist like :include{x}
)"""
)

audio_exclude_string = (
    lambda x: f"""and (
    path not like :exclude{x}
    OR mood not like :exclude{x}
    OR genre not like :exclude{x}
    OR year not like :exclude{x}
    OR bpm not like :exclude{x}
    OR key not like :exclude{x}
    OR time not like :exclude{x}
    OR decade not like :exclude{x}
    OR categories not like :exclude{x}
    OR city not like :exclude{x}
    OR country not like :exclude{x}
    OR description not like :exclude{x}
    OR album not like :exclude{x}
    OR title not like :exclude{x}
    OR artist not like :exclude{x}
)"""
)


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


def extract_metadata(args, f):
    try:
        stat = os.stat(f)
    except:
        return

    if stat.st_size == 0:
        sparseness = 0
    else:
        blocks_allocated = stat.st_blocks * 512
        sparseness = blocks_allocated / stat.st_size

    media = dict(
        path=f,
        size=stat.st_size,
        sparseness=sparseness,
        time_created=stat.st_ctime,
        time_modified=stat.st_mtime,
    )

    if args.db_type == "f":
        media = {**media, "is_dir": os.path.isdir(f)}

    if args.db_type in ["a", "v"]:
        try:
            probe = json.loads(
                cmd(
                    "ffprobe", "-loglevel", "quiet", "-print_format", "json=compact=1", "-show_entries", "format", f
                ).stdout
            )
        except (KeyboardInterrupt, SystemExit):
            exit(130)
        except:
            print(f"Failed reading {f}", file=sys.stderr)
            cmd("trash-put", f, strict=False)
            return
        if not "format" in probe:
            print(f"Failed reading format {f}", file=sys.stderr)
            print(probe)
            return

        assert stat.st_size == int(probe["format"]["size"])

        probe["format"].pop("size", None)
        probe["format"].pop("tags", None)
        probe["format"].pop("format_long_name", None)
        probe["format"].pop("nb_programs", None)
        probe["format"].pop("nb_streams", None)
        probe["format"].pop("probe_score", None)
        probe["format"].pop("start_time", None)
        probe["format"].pop("probe_score", None)
        probe["format"].pop("probe_score", None)

        # raise  ## check probe["streams"]

        media = {
            **media,
            **probe["format"],
            # **streams=probe["streams"],
            "provenance": get_provenance(f),
            "play_count": 0,
        }

    if args.db_type == "v":
        try:
            has_sub = is_file_with_subtitle(f)
        except:
            has_sub = False
        media = {**media, "has_sub": has_sub}

    if args.db_type == "a":
        try:
            tiny_tags = filter_None(TinyTag.get(f).as_dict())
        except:
            tiny_tags = dict()

        try:
            mutagen_tags = filter_None(mutagen.File(f).tags.as_dict())
        except:
            mutagen_tags = dict()

        tags = parse_tags(mutagen_tags, tiny_tags)
        return {**media, **tags}

    return media


def optimize_db(args):
    print("Optimizing database")
    if Path(args.db).exists():
        cmd("sqlite-utils", "optimize", args.db)
        columns = cmd(
            f"sqlite-utils tables {args.db} --columns | jq -r '.[0].columns[]'", shell=True
        ).stdout.splitlines()
        for column in columns:
            cmd("sqlite-utils", "create-index", "--if-not-exists", "--analyze", args.db, "media", column)


def extract_chunk(args, l):
    metadata = (
        Parallel(n_jobs=-1 if args.verbose == 0 else 1, backend="threading")(
            delayed(extract_metadata)(args, file) for file in l
        )
        or []
    )

    DF = pd.DataFrame(list(filter(None, metadata)))

    # if args.db_type == 'a':  # might be dead code
    #     if DF.get(["year"]) is not None:
    #         DF.year = DF.year.astype(str)

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
        scanned_files = [
            str(p) for p in Path(path).resolve().rglob("*")
        ]  # thanks to these people for making rglob fast https://bugs.python.org/issue26032
    new_files = set(scanned_files)

    try:
        existing = set(
            map(lambda x: x["path"], fetchall_dict(args.con, f"select path from media where path like '{path}%'"))
        )
    except:
        scanned_files = list(new_files)
    else:
        scanned_files = list(new_files - existing)

        deleted_files = list(existing - new_files)
        remove_media(args, deleted_files)

        if args.db_type == "v":
            args.con.execute("DELETE from media where path like '%/keep/%'")
        args.con.commit()

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


def extractor(args):
    Path(args.db).touch()
    args.con = sqlite_con(args.db)
    for path in args.paths:
        scan_path(args, path)

    optimize_db(args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db", nargs="?")
    parser.add_argument("paths", nargs="+")

    db_type = parser.add_mutually_exclusive_group()
    db_type.add_argument("-a", "--audio", action="store_const", dest="db_type", const="a")
    db_type.add_argument("-fs", "--filesystem", action="store_const", dest="db_type", const="f")
    db_type.add_argument("--video", action="store_const", dest="db_type", const="v")
    parser.set_defaults(db_type="v")

    parser.add_argument("-s", "--subtitle", action="store_true")
    parser.add_argument("-yt", "--youtube-only", action="store_true")
    parser.add_argument("-sl", "--subliminal-only", action="store_true")
    parser.add_argument("-f", "--force-rescan", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    if not args.db:
        if args.db_type == "a":
            args.db = "audio.db"
        elif args.db_type == "f":
            args.db = "fs.db"
        elif args.db_type == "v":
            args.db = "video.db"
        else:
            raise Exception("db_type unknown")

    if args.force_rescan:
        Path(args.db).unlink(missing_ok=True)

    extractor(args)


if __name__ == "__main__":
    main()