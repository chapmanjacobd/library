import argparse, json, tempfile
from copy import deepcopy
from pathlib import Path

from library import usage
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, consts, db_utils, devices, file_utils, iterables


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.redownload)
    parser.add_argument("--download-archive", default=str(Path("~/.local/share/yt_archive.txt").expanduser().resolve()))
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default="100")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("deleted_at", nargs="?")
    parser.add_argument("deleted_to", nargs="?")
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    return args


def list_deletions(args) -> list[dict]:
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


def get_non_tube_media(args, paths) -> list[dict]:
    media = []
    paths = iterables.conform(paths)
    if paths:
        for p in iterables.chunks(paths, consts.SQLITE_PARAM_LIMIT):
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


def get_deleted_media(args) -> list[dict]:
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
    m_columns = db_utils.columns(args, "media")

    media = deepcopy(deleted_media)
    for d in media:
        d["time_deleted"] = 0
        d["time_modified"] = 0
        d["time_downloaded"] = 0
        d.pop("error", None)

        if "webpath" in m_columns and (d.get("webpath") or "").startswith("http"):
            with args.db.conn:
                args.db.conn.execute("DELETE from media WHERE path = ?", d["path"])

            d["path"] = d["webpath"]
            args.db["media"].upsert(d, alter=True)  # type: ignore
        else:
            args.db["media"].upsert(d, alter=True)  # type: ignore


def print_deleted(args, deleted_media) -> None:
    tbl = deepcopy(deleted_media)
    tbl = iterables.list_dict_filter_bool(tbl, keep_0=False)
    tbl = iterables.list_dict_filter_unique(tbl)
    tbl = tbl[: int(args.limit)]
    media_printer.media_printer(args, tbl, units="deleted media")


def redownload() -> None:
    args = parse_args()

    if args.deleted_at:
        deleted_media = get_deleted_media(args)
    else:
        deletions = list_deletions(args)
        print("Deletions:")
        media_printer.media_printer(args, deletions, units="deletions")
        raise SystemExit(0)

    print_deleted(args, deleted_media)
    paths = [d["path"] for d in deleted_media]
    redownload_ids = [d["extractor_id"] for d in deleted_media if d.get("extractor_id")]
    print(len(redownload_ids), "tube ids found")
    if deleted_media and devices.confirm("Redownload media?"):  # type: ignore
        if len(redownload_ids) > 0:
            download_archive = Path(args.download_archive).expanduser().resolve()
            if download_archive.exists():
                file_utils.filter_file(str(download_archive), redownload_ids)

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
