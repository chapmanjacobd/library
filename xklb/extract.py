import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import mutagen
import pandas as pd
from joblib import Parallel, delayed
from rich import inspect
from tinytag import TinyTag

from .db import fetchall_dict, sqlite_con
from .subtitle import get_subtitle, is_file_with_subtitle, youtube_dl_id
from .utils import chunks, cmd, combine, get_video_files, log, remove_None, safe_unpack

SQLITE_PARAM_LIMIT = 32765


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
        probe = json.loads(
            cmd(
                "ffprobe",
                "-loglevel",
                "quiet",
                "-print_format",
                "json=compact=1",
                "-show_entries",
                "format",
                f,
                quiet=True,
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

    stat = os.stat(f)
    blocks_allocated = stat.st_blocks * 512

    probe["format"].pop("tags", None)
    probe["format"].pop("format_long_name", None)
    probe["format"].pop("nb_programs", None)
    probe["format"].pop("nb_streams", None)
    probe["format"].pop("probe_score", None)
    probe["format"].pop("start_time", None)
    probe["format"].pop("probe_score", None)
    probe["format"].pop("probe_score", None)

    if "size" in probe["format"]:
        probe["format"]["size"] = int(probe["format"]["size"])

    if blocks_allocated == 0:
        sparseness = 0
    else:
        sparseness = probe["format"]["size"] / blocks_allocated

    media = dict(
        **probe["format"],
        # streams=probe["streams"],
        sparseness=sparseness,
        time_created=datetime.fromtimestamp(stat.st_ctime),
        time_modified=datetime.fromtimestamp(stat.st_mtime),
    )

    media = {**media, "provenance": get_provenance(f)}

    if not args.audio:
        try:
            has_sub = is_file_with_subtitle(f)
        except:
            has_sub = False
        media = {**media, "has_sub": has_sub}

    if args.audio:
        media = {**media, "listen_count": 0}

        try:
            tiny_tags = remove_None(TinyTag.get(f).as_dict())
        except:
            tiny_tags = dict()

        try:
            mutagen_tags = remove_None(mutagen.File(f).tags.as_dict())
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
            "sqlite-utils", "tables", args.db, "--columns", "|", "jq", "-r", "'.[0].columns[]'", quiet=True
        ).stdout.splitlines()
        for column in columns:
            cmd("sqlite-utils", "create-index", "--if-not-exists", "--analyze", args.db, "media", column)


def extract_chunk(args, con, l):
    metadata = (
        Parallel(n_jobs=-1 if args.verbose == 0 else 1, backend="threading")(
            delayed(extract_metadata)(args, file) for file in l
        )
        or []
    )

    DF = pd.DataFrame(list(filter(None, metadata)))
    if args.audio:
        if DF.get(["year"]) is not None:
            DF.year = DF.year.astype(str)
    DF.apply(pd.to_numeric, errors="ignore").convert_dtypes().to_sql(  # type: ignore
        "media",
        con=con,
        if_exists="append",
        index=False,
        chunksize=70,
        method="multi",
    )


def find_new_files(args, con, path):
    video_files = get_video_files(path, args.audio)
    new_files = set(video_files)

    try:
        existing = set(
            map(
                lambda x: x["filename"],
                fetchall_dict(con, f"select filename from media where filename like '{path}%'"),
            )
        )
    except:
        video_files = list(new_files)
    else:
        video_files = list(new_files - existing)

        deleted_files = list(existing - new_files)
        if len(deleted_files) > 0:
            print(f"Removing {len(deleted_files)} orphaned metadata")

            df_chunked = chunks(deleted_files, SQLITE_PARAM_LIMIT)
            for l in df_chunked:
                con.execute(
                    "delete from media where filename in (" + ",".join(["?"] * len(l)) + ")",
                    (*l,),
                )
                con.commit()

        con.execute("delete from media where filename like '%/keep/%'")
        con.commit()

    return video_files


def scan_path(args, con, path):
    path = Path(path).resolve()
    print(f"{path} : Scanning...")

    video_files = find_new_files(args, con, path)

    if len(video_files) > 0:
        print(f"Adding {len(video_files)} new media")
        log.debug(video_files)

        batch_count = SQLITE_PARAM_LIMIT // 100
        chunks_count = math.ceil(len(video_files) / batch_count)
        df_chunked = chunks(video_files, batch_count)
        for idx, l in enumerate(df_chunked):
            percent = ((batch_count * idx) + len(l)) / len(video_files) * 100
            print(f"Extracting metadata: {percent:3.1f}% (chunk {idx + 1} of {chunks_count})")
            extract_chunk(args, con, l)

            if args.subtitle:
                print("Fetching subtitles")
                Parallel(n_jobs=5)(delayed(get_subtitle)(args, file) for file in l)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("-a", "--audio", action="store_true")
    parser.add_argument("-s", "--subtitle", action="store_true")
    parser.add_argument("-yt", "--youtube-only", action="store_true")
    parser.add_argument("-sl", "--subliminal-only", action="store_true")
    parser.add_argument("-f", "--force-rescan", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()
    if args.force_rescan:
        Path(args.db).unlink(missing_ok=True)

    Path(args.db).touch()
    con = sqlite_con(args.db)
    for path in args.paths:
        scan_path(args, con, path)

    optimize_db(args)


if __name__ == "__main__":
    main()
