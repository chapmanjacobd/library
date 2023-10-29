import argparse
from copy import deepcopy
from typing import List

from xklb import db_media, usage
from xklb.media import media_printer
from xklb.utils import consts, db_utils, devices, objects
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library merge-online-local", usage=usage.merge_online_local)
    parser.add_argument("--no-confirm", "--yes", "-y", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default=100)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    args = parser.parse_args()
    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))
    return args


def get_duplicates(args) -> List[dict]:
    query = """
    WITH m1 as (
        SELECT
            *
        FROM
            media
        WHERE 1=1
            and extractor_id is not null
            and extractor_id != ""
            and coalesce(time_deleted, 0)=0
            and playlist_id in (
                SELECT id from playlists
                WHERE extractor_key
                    NOT IN ('Local', 'NBCStations', 'TedTalk', 'ThisAmericanLife', 'InfoQ', 'NFB', 'KickStarter')
            )
    )
    SELECT
        m2.path keep_path
        , m1.path duplicate_path
        , m1.title
    FROM m1, (
        SELECT
            media.id,
            *
        FROM
            media
        WHERE 1=1
            and coalesce(time_deleted, 0)=0
            and extractor_id is null
            and title is null
    ) m2
    JOIN media_fts on m2.id = media_fts.rowid
    JOIN playlists p2 on p2.id = m2.playlist_id
    WHERE p2.extractor_key = 'Local'
        AND media_fts.path MATCH '"'||m1.extractor_id||'"'
        AND m2.PATH LIKE '%['||m1.extractor_id||']%'
    ORDER BY 1=1
        , length(m2.path)-length(REPLACE(m2.path, '/', '')) desc
        , length(m2.path)-length(REPLACE(m2.path, '.', ''))
        , length(m2.path)
        , m2.time_modified desc
        , m2.time_created desc
        , m2.duration desc
        , m2.path desc
    """

    return list(args.db.query(query))


def merge_online_local() -> None:
    args = parse_args()
    args.db["media"].rebuild_fts()
    duplicates = get_duplicates(args)

    tbl = deepcopy(duplicates[: int(args.limit)])
    media_printer.media_printer(args, tbl, units="duplicates", media_len=len(duplicates))

    if duplicates and (args.no_confirm or devices.confirm("Merge duplicates?")):  # type: ignore
        log.info("Merging...")

        merged = []
        for d in duplicates:
            fspath = d["keep_path"]
            webpath = d["duplicate_path"]
            if webpath in merged or fspath == webpath:
                continue

            tube_entry = db_media.get(args, webpath)
            fs_tags = db_media.get(args, fspath)

            if not tube_entry or not fs_tags or tube_entry["extractor_id"] not in fs_tags["path"]:
                continue

            if fs_tags["time_modified"] is None or fs_tags["time_modified"] == 0:
                fs_tags["time_modified"] = consts.now()
            if fs_tags["time_downloaded"] is None or fs_tags["time_downloaded"] == 0:
                fs_tags["time_downloaded"] = consts.APPLICATION_START

            entry = {**tube_entry, **fs_tags, "webpath": webpath}
            db_media.add(args, objects.dict_filter_bool(entry))  # type: ignore
            with args.db.conn:
                args.db.conn.execute("DELETE from media WHERE path = ?", [webpath])
            merged.append(webpath)

        print(len(merged), "merged")


if __name__ == "__main__":
    merge_online_local()
