import argparse, operator, tempfile
from copy import deepcopy
from pathlib import Path
from typing import List

import humanize
from rich import prompt
from tabulate import tabulate

from xklb import db, player, utils
from xklb.consts import DBType
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--audio",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Dedupe database by artist + album + title",
    )
    profile.add_argument(
        "--id", action="store_const", dest="profile", const="id", help="Dedupe database by id + ie_key"
    )
    profile.add_argument(
        "--title", action="store_const", dest="profile", const="title", help="Dedupe database by title + uploader"
    )
    profile.add_argument(
        "--filesystem",
        action="store_const",
        dest="profile",
        const=DBType.filesystem,
        help="Dedupe filesystem database",
    )
    profile.add_argument("--text", action="store_const", dest="profile", const=DBType.text, help="Dedupe text database")
    profile.add_argument(
        "--image", action="store_const", dest="profile", const=DBType.image, help="Dedupe image database"
    )

    parser.add_argument("--only-soft-delete", action="store_true")
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default=100)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    args = parser.parse_args()
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def get_music_duplicates(args) -> List[dict]:
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
        , length(m1.path)-length(REPLACE(m1.path, '/', '')) DESC
        , length(m1.path)-length(REPLACE(m1.path, '.', ''))
        , length(m1.path)
        , m1.size DESC
        , m1.time_modified DESC
        , m1.time_created DESC
        , m1.duration DESC
        , m1.path DESC
    """

    media = list(args.db.query(query))

    return media


def get_id_duplicates(args) -> List[dict]:
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
        and m1.id = m2.id
        and m1.duration >= m2.duration - 4
        and m1.duration <= m2.duration + 4
        and m1.ie_key in (m2.ie_key, 'Local')
        and m2.path != m1.path
    WHERE 1=1
        and m1.time_deleted = 0 and m2.time_deleted = 0
        and abs(m1.sparseness - 1) < 0.1
        and m1.id != '' and m1.ie_key != ''
    ORDER BY 1=1
        , m1.video_count > 0 DESC
        , m1.subtitle_count > 0 DESC
        , m1.audio_count DESC
        , length(m1.path)-length(REPLACE(m1.path, '/', '')) DESC
        , length(m1.path)-length(REPLACE(m1.path, '.', ''))
        , length(m1.path)
        , m1.size DESC
        , m1.time_modified DESC
        , m1.time_created DESC
        , m1.duration DESC
        , m1.path DESC
    """

    media = list(args.db.query(query))

    return media


def get_title_duplicates(args) -> List[dict]:
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
    WHERE 1=1
        and m1.time_deleted = 0 and m2.time_deleted = 0
        and abs(m1.sparseness - 1) < 0.1
        and m1.title != '' and m1.uploader != ''
        and m1.title = m2.title and m1.uploader = m2.uploader
    ORDER BY 1=1
        , m1.video_count > 0 DESC
        , m1.subtitle_count > 0 DESC
        , m1.audio_count DESC
        , length(m1.path)-length(REPLACE(m1.path, '/', '')) DESC
        , length(m1.path)-length(REPLACE(m1.path, '.', ''))
        , length(m1.path)
        , m1.size DESC
        , m1.time_modified DESC
        , m1.time_created DESC
        , m1.duration DESC
        , m1.path DESC
    """

    media = list(args.db.query(query))

    return media


def deduplicate_db() -> None:
    args = parse_args()

    if args.profile == DBType.audio:
        duplicates = get_music_duplicates(args)
    elif args.profile == "id":
        duplicates = get_id_duplicates(args)
    elif args.profile == "title":
        duplicates = get_title_duplicates(args)
    elif args.profile == DBType.filesystem:
        print(
            """
        You should use `rmlint` instead:

            $ rmlint --progress --merge-directories --partial-hidden --xattr
        """
        )
        return
    else:
        # TODO: add fts-similarity option...
        raise NotImplementedError

    deletion_candidates = []
    deletion_paths = []
    for d in duplicates:
        if any(
            [
                d["keep_path"] in deletion_paths or d["duplicate_path"] in deletion_paths,
                d["keep_path"] == d["duplicate_path"],
                not Path(d["keep_path"]).resolve().exists(),
            ]
        ):
            continue

        deletion_paths.append(d["duplicate_path"])
        deletion_candidates.append(d)
    duplicates = deletion_candidates

    if not duplicates:
        print("No duplicates found")
        return

    tbl = deepcopy(duplicates)
    tbl = tbl[: int(args.limit)]
    tbl = utils.col_resize(tbl, "keep_path", 30)
    tbl = utils.col_resize(tbl, "duplicate_path", 30)
    tbl = utils.col_naturalsize(tbl, "duplicate_size")
    print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))

    duplicates_count = len(duplicates)
    print(f"{duplicates_count} duplicates found (showing first {args.limit})")

    try:
        import pandas as pd

        csv_path = tempfile.mktemp(".csv")
        pd.DataFrame(duplicates).to_csv(csv_path, index=False)
        print("Full list saved to:", csv_path)
    except ModuleNotFoundError:
        pass

    duplicates_size = sum(filter(None, map(operator.itemgetter("duplicate_size"), duplicates)))
    print(f"Approx. space savings: {humanize.naturalsize(duplicates_size // 2)}")

    if duplicates and (args.force or prompt.Confirm.ask("Delete duplicates?", default=False)):  # type: ignore
        print("Deleting...")
        for d in duplicates:
            path = d["duplicate_path"]
            if not path.startswith("http") and not args.only_soft_delete:
                utils.trash(path, detach=False)
            player.mark_media_deleted(args, path)


if __name__ == "__main__":
    deduplicate_db()
