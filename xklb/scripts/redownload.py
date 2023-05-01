import argparse, json, tempfile
from copy import deepcopy
from pathlib import Path
from typing import List

from tabulate import tabulate

from xklb import consts, db, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="library redownload",
        usage="""library redownload DATABASE

    If you have previously downloaded YouTube or other online media, but your
    hard drive failed or you accidentally deleted something, and if that media
    is still accessible from the same URL, this script can help to redownload
    everything that was scanned-as-deleted between two timestamps.

    List deletions:

        $ library redownload news.db
        Deletions:
        ╒═════════════════════╤═════════╕
        │ time_deleted        │   count │
        ╞═════════════════════╪═════════╡
        │ 2023-01-26T00:31:26 │     120 │
        ├─────────────────────┼─────────┤
        │ 2023-01-26T19:54:42 │      18 │
        ├─────────────────────┼─────────┤
        │ 2023-01-26T20:45:24 │      26 │
        ╘═════════════════════╧═════════╛
        Showing most recent 3 deletions. Use -l to change this limit

    Mark videos as candidates for download via specific deletion timestamp:

        $ library redownload city.db 2023-01-26T19:54:42
        ╒══════════╤════════════════╤═════════════════╤═══════════════════╤═════════╤══════════╤═══════╤══════════════════╤════════════════════════════════════════════════════════════════════════════════════════════════════════╕
        │ size     │ time_created   │ time_modified   │ time_downloaded   │   width │   height │   fps │ duration         │ path                                                                                                   │
        ╞══════════╪════════════════╪═════════════════╪═══════════════════╪═════════╪══════════╪═══════╪══════════════════╪════════════════════════════════════════════════════════════════════════════════════════════════════════╡
        │ 697.7 MB │ Apr 13 2022    │ Mar 11 2022     │ Oct 19            │    1920 │     1080 │    30 │ 21.22 minutes    │ /mnt/d/76_CityVideos/PRAIA DE BARRA DE JANGADA CANDEIAS JABOATÃO                                       │
        │          │                │                 │                   │         │          │       │                  │ RECIFE PE BRASIL AVENIDA BERNARDO VIEIRA DE MELO-4Lx3hheMPmg.mp4
        ...

    ...or between two timestamps inclusive:

        $ library redownload city.db 2023-01-26T19:54:42 2023-01-26T20:45:24

    """,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--download-archive", default="~/.local/share/yt_archive.txt")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default=100)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("deleted_at", nargs="?")
    parser.add_argument("deleted_to", nargs="?")
    args = parser.parse_args()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def list_deletions(args) -> List[dict]:
    query = """
        SELECT
            strftime('%Y-%m-%dT%H:%M:%S', time_deleted, 'unixepoch', 'localtime') as time_deleted
            , COUNT(*) as count
        FROM media
        WHERE time_deleted > 0
            AND time_downloaded > 0
        GROUP BY time_deleted
        HAVING count > 0
        ORDER BY time_deleted DESC
        LIMIT ?
    """
    media = list(args.db.query(query, [args.limit]))
    media = list(reversed(media))
    return media


def get_non_tube_media(args, paths) -> List[dict]:
    media = []
    paths = utils.conform(paths)
    if paths:
        for p in utils.chunks(paths, consts.SQLITE_PARAM_LIMIT):
            with args.db.conn:
                media.extend(
                    list(
                        args.db.query(
                            "select * from media where path in (" + ",".join(["?"] * len(p)) + ")",
                            (*p,),
                        ),
                    ),
                )
    return media


def get_deleted_media(args) -> List[dict]:
    if all([args.deleted_at, args.deleted_to]):
        # use timestamps between inclusive, converting from localtime to UTC
        query = """
            SELECT *
            FROM media
            WHERE time_deleted >= strftime('%s', ?, 'utc') AND time_deleted <= strftime('%s', ?, 'utc')
            AND time_downloaded > 0
        """
        media = list(args.db.query(query, (args.deleted_at, args.deleted_to)))
    else:
        # use exact timestamp, converting from localtime to UTC
        query = """
            SELECT *
            FROM media
            WHERE time_deleted = strftime('%s', ?, 'utc')
            AND time_downloaded > 0
        """
        media = list(args.db.query(query, (args.deleted_at,)))
    return media


def mark_media_undownloaded(args, deleted_media) -> None:
    m_columns = args.db["media"].columns_dict

    media = deepcopy(deleted_media)
    for d in media:
        d["time_deleted"] = 0
        d["time_modified"] = 0
        d["time_downloaded"] = 0
        d.pop("error", None)

        if "webpath" in m_columns and (d.get("webpath") or "").startswith("http"):
            args.db["media"].delete(d["path"])  # type: ignore

            d["path"] = d["webpath"]
            args.db["media"].upsert(d, pk="path", alter=True)  # type: ignore
        else:
            args.db["media"].upsert(d, pk="path", alter=True)  # type: ignore


def print_deletions(args, deletions) -> None:
    print("Deletions:")
    tbl = deepcopy(deletions)
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))
    print(f"Showing most recent {args.limit} deletions. Use -l to change this limit")


def print_deleted(args, deleted_media) -> None:
    tbl = deepcopy(deleted_media)
    tbl = utils.list_dict_filter_bool(tbl, keep_0=False)
    tbl = utils.list_dict_filter_unique(tbl)
    tbl = utils.list_dict_filter_keys(tbl, ["sparseness"])
    tbl = tbl[: int(args.limit)]
    tbl = utils.col_resize(tbl, "path", 25)
    tbl = utils.col_duration(tbl, "duration")
    tbl = utils.col_naturalsize(tbl, "size")
    for t in consts.TIME_COLUMNS:
        utils.col_naturaldate(tbl, t)
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))
    print(f"{len(deleted_media)} deleted media found (showing first {args.limit})")


def redownload() -> None:
    args = parse_args()

    if args.deleted_at:
        deleted_media = get_deleted_media(args)
    else:
        deletions = list_deletions(args)
        print_deletions(args, deletions)
        raise SystemExit(0)

    print_deleted(args, deleted_media)
    paths = [d["path"] for d in deleted_media]
    redownload_ids = [d["id"] for d in deleted_media if d.get("id")]
    print(len(redownload_ids), "tube ids found")
    if deleted_media and utils.confirm("Redownload media?"):  # type: ignore
        if len(redownload_ids) > 0:
            download_archive = Path(args.download_archive).expanduser().resolve()
            if download_archive.exists():
                utils.filter_file(str(download_archive), redownload_ids)

        mark_media_undownloaded(args, deleted_media)
        non_tube_media = get_non_tube_media(args, paths)

        print("Marked", len(deleted_media) - len(non_tube_media), "records as downloadable. Redownload via lb download")
        if len(non_tube_media) > 0:
            try:
                import pandas as pd

                out_path = tempfile.mktemp(".csv")
                pd.DataFrame(non_tube_media).to_csv(out_path, index=False)
            except ModuleNotFoundError:
                out_path = tempfile.mktemp(".json")
                with open(out_path, "w") as jf:
                    json.dump(non_tube_media, jf)
            print(
                len(non_tube_media),
                "records not recognized as tube media, which you will need to redownload manually. Exported to this temp file:",
                out_path,
            )


if __name__ == "__main__":
    redownload()
