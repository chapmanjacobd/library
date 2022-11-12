import argparse, operator
from copy import deepcopy
from typing import List

import humanize
from rich import print, prompt
from tabulate import tabulate

from xklb import db, player, utils
from xklb.utils import log


def get_duplicates(args) -> List[dict]:
    query = f"""
    SELECT
        m1.path keep_path
        -- , length(m1.path)-length(REPLACE(m1.path, '/', '')) num_slash
        -- , length(m1.path)-length(REPLACE(m1.path, '.', '')) num_dot
        -- , length(m1.path) len_p
        , m2.path duplicate_path
        , m2.size duplicate_size
    FROM
        media m1
    JOIN media m2 on 1=1
        and m2.path != m1.path
        and m1.duration >= m2.duration - 4
        and m1.duration <= m2.duration + 4
        and m1.title = m2.title
        and m1.artist = m2.artist
        and m1.album = m2.album
    WHERE 1=1
        and m1.time_deleted = 0 and m2.time_deleted = 0
        and m1.audio_count > 0 and m2.audio_count > 0
        and abs(m1.sparseness - 1) < 0.1
        and m1.title != ''
        and m1.artist != ''
        and m1.album != ''
    ORDER BY 1=1
        , length(m1.path)-length(REPLACE(m1.path, '/', '')) desc
        , length(m1.path)-length(REPLACE(m1.path, '.', ''))
        , length(m1.path)
        , m1.size desc
        , m1.time_modified desc
        , m1.time_created desc
        , m1.duration desc
        , m1.path desc
    """

    media = list(args.db.query(query))

    return media


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("--only-soft-delete", action="store_true")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default=100)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def deduplicate_music() -> None:
    args = parse_args()
    duplicates = get_duplicates(args)
    duplicates_count = len(duplicates)
    duplicates_size = sum(map(operator.itemgetter("duplicate_size"), duplicates))

    tbl = deepcopy(duplicates)
    tbl = tbl[: int(args.limit)]  # TODO: export to CSV
    tbl = utils.col_resize(tbl, "keep_path", 30)
    tbl = utils.col_resize(tbl, "duplicate_path", 30)
    tbl = utils.col_naturalsize(tbl, "duplicate_size")
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))

    print(f"{duplicates_count} duplicates found (showing first {args.limit})")
    print(f"Approx. space savings: {humanize.naturalsize(duplicates_size // 2)}")
    print(
        "Warning! This script assumes that the database is up to date. If you have deleted any files manually, run a re-scan (via fsadd) for each folder in your database first!"
    )

    if duplicates and prompt.Confirm.ask("Delete duplicates?", default=False):  # type: ignore
        print("Deleting...")

        deleted = []
        for d in duplicates:
            if d["keep_path"] in deleted:
                continue

            path = d["duplicate_path"]
            if not args.only_soft_delete:
                utils.trash(path)
            player.mark_media_deleted(args, path)
            deleted.append(path)

        print(len(deleted), "deleted")


if __name__ == "__main__":
    deduplicate_music()
