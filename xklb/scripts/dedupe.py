import argparse, re, tempfile
from copy import deepcopy
from pathlib import Path
from typing import List

import humanize
from rich import print

from xklb import consts, db, player, usage, utils
from xklb.consts import DBType
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library dedupe", usage=usage.dedupe)

    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--audio",
        action="store_const",
        dest="profile",
        const=DBType.audio,
        help="Dedupe database by artist + album + title",
    )
    profile.add_argument(
        "--extractor-id",
        "--id",
        action="store_const",
        dest="profile",
        const="extractor_id",
        help="Dedupe database by extractor_id",
    )
    profile.add_argument(
        "--title",
        action="store_const",
        dest="profile",
        const="title",
        help="Dedupe database by title",
    )
    profile.add_argument(
        "--duration",
        action="store_const",
        dest="profile",
        const="duration",
        help="Dedupe database by duration (caution obviously)",
    )
    profile.add_argument(
        "--fts",
        action="store_const",
        dest="profile",
        const="fts",
        help=argparse.SUPPRESS,
    )
    profile.add_argument(
        "--filesystem",
        action="store_const",
        dest="profile",
        const=DBType.filesystem,
        help="Dedupe filesystem database",
    )
    profile.add_argument(
        "--text",
        action="store_const",
        dest="profile",
        const=DBType.text,
        help=argparse.SUPPRESS,
        #  "Dedupe text database",
    )
    profile.add_argument(
        "--image",
        action="store_const",
        dest="profile",
        const=DBType.image,
        help=argparse.SUPPRESS,
        # "Dedupe image database",
    )
    profile.set_defaults(profile="audio")

    parser.add_argument("--only-soft-delete", action="store_true")
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", default=100)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--print", "-p", default="", const="p", nargs="?")
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a column when printing")
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    args.db = db.connect(args)

    args.filter_sql = []
    args.filter_bindings = {}

    COMPARE_DIRS = False
    if len(args.include + args.paths) == 2:
        COMPARE_DIRS = True
        if len(args.include) == 2:
            include2 = args.include.pop()
            args.table2, search_bindings = db.fts_search_sql(
                "media",
                fts_table=args.db["media"].detect_fts(),
                include=include2,
                exclude=args.exclude,
            )
            args.filter_bindings = {**args.filter_bindings, **search_bindings}
        else:
            path2 = args.paths.pop()
            args.table2 = "(select * from media where path like :path2)"
            for idx, path in enumerate(args.paths):
                args.filter_bindings[f"path2"] = path2.replace(" ", "%").replace("%%", " ") + "%"

    args.table = "media"
    if args.db["media"].detect_fts() and args.include:  # type: ignore
        args.table, search_bindings = db.fts_search_sql(
            "media",
            fts_table=args.db["media"].detect_fts(),
            include=args.include,
            exclude=args.exclude,
        )
        args.filter_bindings = {**args.filter_bindings, **search_bindings}
    elif args.paths:
        args.table = (
            "(select * from media where 1=1"
            " and (" + " OR ".join(f"path like :path{idx}" for idx in range(len(args.paths))) + ")"
            ")"
        )
        for idx, path in enumerate(args.paths):
            args.filter_bindings[f"path{idx}"] = path.replace(" ", "%").replace("%%", " ") + "%"

    if not COMPARE_DIRS:
        args.table2 = args.table

    args.action = consts.SC.dedupe
    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def get_rows(args) -> List[dict]:
    query = f"""
    SELECT
        {', '.join(db.config["media"]["search_columns"])}
    FROM
        {args.table}
    WHERE 1=1
        and time_deleted = 0
        and audio_count > 0
        and duration is not null
        and path not like 'http%'
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        , length(path)-length(REPLACE(path, '/', '')) DESC
        , length(path)-length(REPLACE(path, '.', ''))
        , length(path)
        , size DESC
        , time_modified DESC
        , time_created DESC
        , duration DESC
        , path DESC
    """

    return args.db.query(query, args.filter_bindings)


def get_music_duplicates(args) -> List[dict]:
    m_columns = db.columns(args, "media")
    query = f"""
    SELECT
        m1.path keep_path
        -- , length(m1.path)-length(REPLACE(m1.path, '/', '')) num_slash
        -- , length(m1.path)-length(REPLACE(m1.path, '.', '')) num_dot
        -- , length(m1.path) len_p
        , m2.path duplicate_path
        , m2.size duplicate_size
    FROM
        {args.table} m1
    JOIN {args.table2} m2 on 1=1
        and m2.path != m1.path
        and m1.duration >= m2.duration - 4
        and m1.duration <= m2.duration + 4
        and m1.title = m2.title
        {"and m1.artist = m2.artist" if 'artist' in m_columns else ''}
        {"and m1.album = m2.album" if 'album' in m_columns else ''}
    WHERE 1=1
        and coalesce(m1.time_deleted,0) = 0 and coalesce(m2.time_deleted,0) = 0
        and m1.title != ''
        {"and m1.artist != ''" if 'artist' in m_columns else ''}
        {"and m1.album != ''" if 'album' in m_columns else ''}
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        {', m1.video_count > 0 DESC' if 'video_count' in m_columns else ''}
        {', m1.subtitle_count > 0 DESC' if 'subtitle_count' in m_columns else ''}
        {', m1.audio_count > 0 DESC' if 'audio_count' in m_columns else ''}
        {', m1.uploader IS NOT NULL DESC' if 'uploader' in m_columns else ''}
        , length(m1.path)-length(REPLACE(m1.path, '/', '')) DESC
        , length(m1.path)-length(REPLACE(m1.path, '.', ''))
        , length(m1.path)
        , m1.size DESC
        , m1.time_modified DESC
        , m1.time_created DESC
        , m1.duration DESC
        , m1.path DESC
    """

    media = list(args.db.query(query, args.filter_bindings))

    return media


def get_id_duplicates(args) -> List[dict]:
    m_columns = db.columns(args, "media")
    query = f"""
    SELECT
        m1.path keep_path
        -- , length(m1.path)-length(REPLACE(m1.path, '/', '')) num_slash
        -- , length(m1.path)-length(REPLACE(m1.path, '.', '')) num_dot
        -- , length(m1.path) len_p
        , m2.path duplicate_path
        , m2.size duplicate_size
    FROM
        {args.table} m1
    JOIN {args.table2} m2 on 1=1
        and m1.extractor_id = m2.extractor_id
        and m1.duration >= m2.duration - 4
        and m1.duration <= m2.duration + 4
        and m2.path != m1.path
    WHERE 1=1
        and coalesce(m1.time_deleted,0) = 0 and coalesce(m2.time_deleted,0) = 0
        and m1.extractor_id != ''
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        , m1.video_count > 0 DESC
        {', m1.subtitle_count > 0 DESC' if 'subtitle_count' in m_columns else ''}
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

    media = list(args.db.query(query, args.filter_bindings))

    return media


def get_title_duplicates(args) -> List[dict]:
    m_columns = db.columns(args, "media")
    query = f"""
    SELECT
        m1.path keep_path
        -- , length(m1.path)-length(REPLACE(m1.path, '/', '')) num_slash
        -- , length(m1.path)-length(REPLACE(m1.path, '.', '')) num_dot
        -- , length(m1.path) len_p
        , m2.path duplicate_path
        , m2.size duplicate_size
    FROM
        {args.table} m1
    JOIN {args.table2} m2 on 1=1
        and m2.path != m1.path
        and m1.duration >= m2.duration - 4
        and m1.duration <= m2.duration + 4
    WHERE 1=1
        and coalesce(m1.time_deleted,0) = 0 and coalesce(m2.time_deleted,0) = 0
        and m1.title != '' and m1.title = m2.title
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        , m1.video_count > 0 DESC
        {', m1.subtitle_count > 0 DESC' if 'subtitle_count' in m_columns else ''}
        , m1.audio_count DESC
        , m1.uploader IS NOT NULL DESC
        , length(m1.path)-length(REPLACE(m1.path, '/', '')) DESC
        , length(m1.path)-length(REPLACE(m1.path, '.', ''))
        , length(m1.path)
        , m1.size DESC
        , m1.time_modified DESC
        , m1.time_created DESC
        , m1.duration DESC
        , m1.path DESC
    """

    media = list(args.db.query(query, args.filter_bindings))

    return media


def get_duration_duplicates(args) -> List[dict]:
    m_columns = db.columns(args, "media")
    query = f"""
    SELECT
        m1.path keep_path
        -- , length(m1.path)-length(REPLACE(m1.path, '/', '')) num_slash
        -- , length(m1.path)-length(REPLACE(m1.path, '.', '')) num_dot
        -- , length(m1.path) len_p
        , m2.path duplicate_path
        , m2.size duplicate_size
    FROM
        {args.table} m1
    JOIN {args.table2} m2 on 1=1
        and m2.path != m1.path
        and m1.duration >= m2.duration - 4
        and m1.duration <= m2.duration + 4
    WHERE 1=1
        and coalesce(m1.time_deleted,0) = 0 and coalesce(m2.time_deleted,0) = 0
        and m1.duration = m2.duration
        {" ".join(args.filter_sql)}
    ORDER BY 1=1
        , m1.video_count > 0 DESC
        {', m1.subtitle_count > 0 DESC' if 'subtitle_count' in m_columns else ''}
        , m1.audio_count DESC
        , m1.uploader IS NOT NULL DESC
        , length(m1.path)-length(REPLACE(m1.path, '/', '')) DESC
        , length(m1.path)-length(REPLACE(m1.path, '.', ''))
        , length(m1.path)
        , m1.size DESC
        , m1.time_modified DESC
        , m1.time_created DESC
        , m1.duration DESC
        , m1.path DESC
    """

    media = list(args.db.query(query, args.filter_bindings))

    return media


def filter_split_files(paths):
    pattern = r"\.\d{3,5}\."
    return filter(lambda x: not re.search(pattern, x), paths)


def dedupe() -> None:
    args = parse_args()

    if args.profile == DBType.audio:
        duplicates = get_music_duplicates(args)
    elif args.profile == "extractor_id":
        duplicates = get_id_duplicates(args)
    elif args.profile == "title":
        duplicates = get_title_duplicates(args)
    elif args.profile == "duration":
        duplicates = get_duration_duplicates(args)
    elif args.profile == DBType.filesystem:
        print(
            """
        You should use `rmlint` instead:

            $ rmlint --progress --merge-directories --partial-hidden --xattr
        """,
        )
        return
    elif args.profile == DBType.image:
        print(
            """
        You should use `cbird` instead:

            $ cbird -i.algos 1 -update
            $ cbird -dups -select-result -sort-rev resolution -chop -nuke  # exact duplicates
            $ cbird -p.dht 1 -similar -select-result -sort-rev resolution -chop -nuke  # similar photos
        """,
        )
        return
    elif args.profile == "fts":
        m_columns = db.columns(args, "media")
        m_columns.update(rank=int)
        fts_table = args.db["media"].detect_fts()

        rows = get_rows(args)
        for row in rows:
            words = set(utils.conform(utils.extract_words(Path(v).stem if k == "path" else v) for k, v in row.items()))
            table, search_bindings = db.fts_search_sql(
                "media",
                fts_table=fts_table,
                include=sorted(words, key=len, reverse=True)[:100],
                exclude=args.exclude,
                flexible=False,
            )

            query = f"""
                SELECT path
                FROM {table} m
                WHERE path in (select path from {args.table})
                ORDER BY
                    video_count > 0 DESC
                    {', subtitle_count > 0 DESC' if 'subtitle_count' in m_columns else ''}
                    , audio_count DESC
                    , length(path)-length(REPLACE(path, '/', '')) DESC
                    , length(path)-length(REPLACE(path, '.', ''))
                    , length(path)
                    , size DESC
                    , time_modified DESC
                    , time_created DESC
                    , duration DESC
                    , path DESC
                    , path
                {"LIMIT " + str(args.limit) if args.limit else ""}
                """

            related_media = set(
                filter_split_files(d["path"] for d in args.db.query(query, {**args.filter_bindings, **search_bindings}))
            )
            if len(related_media) > 1:
                print("Found", len(related_media) - 1, "duplicates")
                print(related_media)

                breakpoint()  # TODO: get this working...

        return
    else:
        raise NotImplementedError

    deletion_candidates = []
    deletion_paths = []
    for d in duplicates:
        if any(
            [
                d["keep_path"] in deletion_paths or d["duplicate_path"] in deletion_paths,
                d["keep_path"] == d["duplicate_path"],
                not Path(d["keep_path"]).resolve().exists(),
            ],
        ):
            continue

        deletion_paths.append(d["duplicate_path"])
        deletion_candidates.append(d)
    duplicates = deletion_candidates

    if not duplicates:
        log.error("No duplicates found")
        return

    tbl = deepcopy(duplicates)
    tbl = tbl[: int(args.limit)]
    player.media_printer(args, tbl, units="duplicates", media_len=len(duplicates))

    try:
        import pandas as pd

        csv_path = tempfile.mktemp(".csv")
        pd.DataFrame(duplicates).to_csv(csv_path, index=False)
        print("Full list saved to:", csv_path)
    except ModuleNotFoundError:
        log.info("Skipping CSV export because pandas is not installed")

    duplicates_size = sum(filter(None, [d["duplicate_size"] for d in duplicates]))
    print(f"Approx. space savings: {humanize.naturalsize(duplicates_size // 2)}")

    if duplicates and (args.force or utils.confirm("Delete duplicates?")):  # type: ignore
        log.info("Deleting...")
        for d in duplicates:
            path = d["duplicate_path"]
            if not path.startswith("http") and not args.only_soft_delete:
                utils.trash(path, detach=False)
            player.mark_media_deleted(args, path)


if __name__ == "__main__":
    dedupe()
