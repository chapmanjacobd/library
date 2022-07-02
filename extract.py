import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from shlex import quote

import fuckit
import mutagen
import pandas as pd
from joblib import Parallel, delayed
from rich import inspect, print
from tinytag import TinyTag

from db import fetchall_dict, sqlite_con
from subtitle import get_subtitle
from utils import chunks, cmd, get_video_files, log


def parse_mutagen_tags(m, tiny_tags):
    def c(l):
        if isinstance(l, str):
            l = [l]

        if l is None or len(l) == 0:
            return None

        no_comma = sum([s.split(",") for s in l], [])
        no_semicol = sum([s.split(";") for s in no_comma], [])
        no_unknown = [x for x in no_semicol if x.lower() not in ["unknown", ""]]
        return ";".join(no_unknown)

    def ss(idx, l):
        if l is None:
            return None
        try:
            return l[idx]
        except IndexError:
            return None

    return {
        "albumgenre": c(m.tags.get("albumgenre")),
        "albumgrouping": c(m.tags.get("albumgrouping")),
        "mood": c(
            list(
                set(
                    (m.tags.get("albummood") or [])
                    + (m.tags.get("MusicMatch_Situation") or [])
                    + (m.tags.get("Songs-DB_Occasion") or [])
                )
            )
        ),
        "genre": c(list(set((m.tags.get("genre") or []) + list(filter(None, [tiny_tags["genre"]]))))),
        "year": ss(
            0,
            ss(
                0,
                list(
                    filter(
                        None,
                        [
                            m.tags.get("originalyear"),
                            m.tags.get("TDOR"),
                            m.tags.get("TORY"),
                            m.tags.get("date"),
                            m.tags.get("TDRC"),
                            m.tags.get("TDRL"),
                        ],
                    )
                ),
            ),
        ),
        "bpm": ss(
            0,
            ss(
                0,
                list(
                    filter(
                        None,
                        [m.tags.get("fBPM"), m.tags.get("bpm_accuracy")],
                    )
                ),
            ),
        ),
        "key": ss(
            0,
            ss(
                0,
                list(
                    filter(
                        None,
                        [
                            m.tags.get("TIT1"),
                            m.tags.get("key_accuracy"),
                            m.tags.get("TKEY"),
                        ],
                    )
                ),
            ),
        ),
        "gain": ss(0, m.tags.get("replaygain_track_gain")),
        "time": c(ss(0, m.tags.get("time_signature"))),
        "decade": ss(0, m.tags.get("Songs-DB_Custom1")),
        "categories": ss(0, m.tags.get("Songs-DB_Custom2")),
        "city": ss(0, m.tags.get("Songs-DB_Custom3")),
        "country": c(
            ss(
                0,
                list(
                    filter(
                        None,
                        [
                            m.tags.get("Songs-DB_Custom4"),
                            m.tags.get("MusicBrainz Album Release Country"),
                        ],
                    )
                ),
            )
        ),
    }


def extract_metadata(args, f):
    try:
        ffprobe = json.loads(
            cmd(
                f"ffprobe -loglevel quiet -print_format json=compact=1 -show_entries format {quote(f)}", quiet=True
            ).stdout
        )
    except:
        try:
            cmd(f"trash-put {quote(f)}")
            print(f"Failed reading {f}", file=sys.stderr)
        except:
            pass
        return

    if not "format" in ffprobe:
        print(f"Failed reading format {f}", file=sys.stderr)
        print(ffprobe)
        return

    stat = os.stat(f)
    blocks_allocated = stat.st_blocks * 512

    if "tags" in ffprobe["format"]:
        del ffprobe["format"]["tags"]

    if "size" in ffprobe["format"]:
        ffprobe["format"]["size"] = int(ffprobe["format"]["size"])

    if blocks_allocated == 0:
        sparseness = 0
    else:
        sparseness = ffprobe["format"]["size"] / blocks_allocated

    media = dict(
        **ffprobe["format"],
        # streams=ffprobe["streams"],
        sparseness=sparseness,
        time_created=datetime.fromtimestamp(stat.st_ctime),
        time_modified=datetime.fromtimestamp(stat.st_mtime),
    )

    if args.audio:
        media = {**media, "listen_count": 0}

        try:
            tiny_tags = TinyTag.get(f).as_dict()
            mutagen_tags = mutagen.File(f)
            assert mutagen_tags.tags
            if "extra" in tiny_tags:
                del tiny_tags["extra"]
        except:
            return media

        mutagen_tags_p = parse_mutagen_tags(mutagen_tags, tiny_tags)

        audio = {
            **media,
            **tiny_tags,
            **mutagen_tags_p,
        }
        # print(audio)

        @fuckit
        def get_rid_of_known_tags():
            del mutagen_tags.tags["encoder"]
            del mutagen_tags.tags["TMED"]
            del mutagen_tags.tags["TSO2"]
            del mutagen_tags.tags["artist-sort"]
            del mutagen_tags.tags["ASIN"]
            del mutagen_tags.tags["Acoustid Id"]
            del mutagen_tags.tags["Artists"]
            del mutagen_tags.tags["BARCODE"]
            del mutagen_tags.tags["CATALOGNUMBER"]
            del mutagen_tags.tags["MusicBrainz Album Artist Id"]
            del mutagen_tags.tags["MusicBrainz Album Id"]
            del mutagen_tags.tags["MusicBrainz Album Release Country"]
            del mutagen_tags.tags["MusicBrainz Album Status"]
            del mutagen_tags.tags["MusicBrainz Album Type"]
            del mutagen_tags.tags["MusicBrainz Artist Id"]
            del mutagen_tags.tags["MusicBrainz Release Group Id"]
            del mutagen_tags.tags["MusicBrainz Release Track Id"]
            del mutagen_tags.tags["SCRIPT"]
            del mutagen_tags.tags["originalyear"]
            del mutagen_tags.tags["artist"]
            del mutagen_tags.tags["album"]
            del mutagen_tags.tags["ALBUMARTIST"]
            del mutagen_tags.tags["title"]
            del mutagen_tags.tags["TORY"]
            del mutagen_tags.tags["TDOR"]
            del mutagen_tags.tags["publisher"]
            del mutagen_tags.tags["TRACKNUMBER"]
            del mutagen_tags.tags["DISCNUMBER"]
            del mutagen_tags.tags["replaygain_track_peak"]
            del mutagen_tags.tags["replaygain_track_gain"]
            del mutagen_tags.tags["date"]

            return mutagen_tags.tags

        new_tags = get_rid_of_known_tags()
        if new_tags is not None:
            print(new_tags)

        return audio

    return media


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

    if Path(args.db).exists():
        cmd(f"sqlite-utils optimize {args.db}")
        columns = cmd(
            f"sqlite-utils tables {args.db} --columns | jq -r '.[0].columns[]' ", quiet=True
        ).stdout.splitlines()
        for column in columns:
            cmd(f"sqlite-utils create-index --if-not-exists --analyze {args.db} media {column}")

    con = sqlite_con(args.db)
    for path in args.paths:
        path = Path(path).resolve()
        print(f"{path} : Scanning...")

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

                df_chunked = chunks(deleted_files, 32765)  # sqlite_param_limit
                for l in df_chunked:
                    con.execute(
                        "delete from media where filename in (" + ",".join(["?"] * len(l)) + ")",
                        (*l,),
                    )
                    con.commit()

            con.execute("delete from media where filename like '%/keep/%'")
            con.commit()

        if len(video_files) > 0:
            print(f"Adding {len(video_files)} new media")
            log.info(video_files)

            metadata = (
                Parallel(n_jobs=-1 if args.verbose == 0 else 1, backend="threading")(
                    delayed(extract_metadata)(args, file) for file in video_files
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

            if args.subtitle:
                Parallel(n_jobs=5)(delayed(get_subtitle)(args, file) for file in video_files)


if __name__ == "__main__":
    main()
