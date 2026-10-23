import sys

from library import usage
from library.database.add import tube_backend
from library.database.manage import db_playlists
from library.play import media_printer, post_actions
from library.utils import arggroups, argparse_utils, consts, db_utils, devices, iterables, shell_utils, strings
from library.utils.log_utils import log

MAX_PREVIEW_LENGTH = 80
MIN_PLAYLIST_PATH_PARTS = 2


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.block)
    arggroups.extractor(parser)
    arggroups.text_filtering(parser)
    arggroups.cluster_sort(parser)
    arggroups.regex_sort(parser)

    parser.add_argument("--match-column", "-c", default="path", help="Column to block media if text matches")

    parser.add_argument("--min-tried", default=0, type=int)
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--offline", "--no-tube", action="store_true")
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true")
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser, required=False)

    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.extractor_post(args)
    arggroups.regex_sort_post(args)

    return args


def add_to_blocklist(args, p):
    p = p.pop()
    if args.simulate:
        print("Would add to blocklist:", p)
    else:
        args.db["blocklist"].insert(
            {"key": args.match_column, "value": p}, alter=True, replace=True, pk=["key", "value"]
        )


def remove_from_blocklist(args, p):
    p = p.pop()
    if args.simulate:
        print("Would remove from blocklist:", p)
    else:
        with args.db.conn:
            args.db["blocklist"].delete([args.match_column, p])


def _cleanup_blocklist(args, m_columns):
    if "blocklist" not in args.db.table_names():
        return

    deleted_count = 0
    blocklist_rows = list(args.db["blocklist"].rows)
    playlist_blocklist = [row["value"] for row in blocklist_rows if row["key"] == "playlist_path"]
    playlist_ids = db_playlists.get_ids(args, playlist_blocklist)
    if playlist_ids and not args.simulate:
        with args.db.conn:
            cursor = args.db.conn.execute(
                f"""UPDATE playlists
                SET time_deleted = {consts.APPLICATION_START}
                WHERE id IN ("""
                + ",".join(["?"] * len(playlist_ids))
                + ")",
                (*playlist_ids,),
            )
            deleted_count += cursor.rowcount
            cursor = args.db.conn.execute(
                f"""UPDATE media
                SET time_deleted = {consts.APPLICATION_START}
                WHERE COALESCE(time_deleted, 0)=0
                AND path LIKE 'http%'
                AND playlists_id IN ("""
                + ",".join(["?"] * len(playlist_ids))
                + ")",
                (*playlist_ids,),
            )
            deleted_count += cursor.rowcount

    blocklist = [(row["key"], row["value"]) for row in blocklist_rows if row["key"] in m_columns]
    for chunk in iterables.chunks(blocklist, consts.SQLITE_PARAM_LIMIT // 100):
        if args.simulate:
            continue
        columns = [item[0] for item in chunk]
        values = [item[1] for item in chunk]
        try:
            with args.db.conn:
                query = (
                    f"""UPDATE media
                    SET time_deleted = {consts.APPLICATION_START}
                    WHERE COALESCE(time_deleted, 0)=0
                    AND path LIKE "http%"
                    AND ("""
                    + " OR ".join(f"{column} LIKE ?" for column in columns)
                    + ")"
                )
                cursor = args.db.conn.execute(query, values)
            deleted_count += cursor.rowcount
        except Exception:
            log.exception("Quick cleanup %s", chunk)
            raise

    if deleted_count > 0:
        log.info(f"Marked {deleted_count} blocked metadata records as deleted")


def _show_block_candidates(args, m_columns):
    _cleanup_blocklist(args, m_columns)
    args.match_column = "coalesce(webpath, path)"
    candidates = list(
        args.db.query(
            f"""WITH m as (
                SELECT
                    'http%//' || SUBSTR({args.match_column}
                        , INSTR({args.match_column}, '//') + 2
                        , INSTR( SUBSTR({args.match_column}, INSTR({args.match_column}, '//') + 2), '/') - 1
                    ) || '%' AS subdomain
                    , COUNT(*) as count
                    , COUNT(*) filter (where coalesce(time_modified, 0)=0) AS new_links
                    , COUNT(*) filter (where time_modified>0) AS tried
                    , cast(COUNT(*) filter (where time_modified>0) as float) / COUNT(*) AS percent_tried
                    , COUNT(*) filter (where time_downloaded>0) AS succeeded
                    , coalesce(cast(COUNT(*) filter (where time_downloaded > 0 and time_modified > 0) as float) / COUNT(*) filter (where time_modified > 0), 0) AS percent_succeeded
                    , COUNT(*) filter (where coalesce(time_downloaded, 0)=0 AND coalesce(time_modified, 0)>0) AS failed
                    , coalesce(cast(COUNT(*) filter (where coalesce(time_downloaded, 0)=0 AND coalesce(time_modified, 0)>0) as float) / COUNT(*) filter (where time_modified > 0), 0) AS percent_failed
                FROM media
                WHERE coalesce(time_deleted, 0)=0
                    AND {args.match_column} LIKE 'http%'
                    AND subdomain != "http%///%"
                GROUP BY subdomain
            )
            SELECT * from m
            WHERE count != tried
              AND new_links >= 15
              AND tried >= {args.min_tried}
            ORDER BY tried > 0 DESC
                , percent_succeeded >= 1.0 and failed = 0
                , tried > 15 DESC
                , succeeded = 0 DESC
                , percent_failed < 0.3
                , ntile(5) over (order by new_links) desc
                , percent_failed >= 0.7 DESC
                , ntile(3) over (order by tried) desc
                , ntile(3) over (order by succeeded) desc
                , subdomain
            """,
        ),
    )
    media_printer.media_printer(args, candidates, units="subdomains")


def _block_playlist_paths(args, paths):
    playlist_paths = list(paths)
    for playlist_path in playlist_paths:
        add_to_blocklist(args, [playlist_path])

    playlist_ids = db_playlists.get_ids(args, playlist_paths)
    if not args.simulate and playlist_ids:
        with args.db.conn:
            args.db.conn.execute(
                f"""UPDATE playlists
                SET time_deleted={consts.APPLICATION_START}
                WHERE id IN ("""
                + ",".join(["?"] * len(playlist_ids))
                + ")",
                (*playlist_ids,),
            )
            args.db.conn.execute(
                f"""UPDATE media
                SET time_deleted={consts.APPLICATION_START}
                WHERE path LIKE 'http%'
                AND playlists_id IN ("""
                + ",".join(["?"] * len(playlist_ids))
                + ")",
                (*playlist_ids,),
            )

    if not playlist_ids:
        return
    playlist_media = list(
        args.db.query(
            """SELECT path, size FROM media
            WHERE coalesce(time_deleted, 0)=0
            AND time_downloaded > 0
            AND playlists_id IN ("""
            + ",".join(["?"] * len(playlist_ids))
            + ")",
            (*playlist_ids,),
        ),
    )
    total_size = sum(row["size"] or 0 for row in playlist_media)
    paths_to_delete = [row["path"] for row in playlist_media]
    if not paths_to_delete:
        return
    print(paths_to_delete)
    if not args.simulate and devices.confirm(
        f"Would you like to delete these {len(paths_to_delete)} local files ({strings.file_size(total_size)})?",
    ):
        post_actions.delete_media(args, paths_to_delete)
    elif args.simulate:
        print("Would delete local files:", *paths_to_delete, sep="\n")


def _get_matching_media(args, select_sql, path):
    matching_media = list(
        args.db.query(
            f"select {select_sql} from media where coalesce(time_deleted, 0)=0 AND {args.match_column} LIKE ?",
            (path,),
        ),
    )
    if matching_media:
        return matching_media

    matching_media = list(
        args.db.query(
            f"select {select_sql} from media where coalesce(time_deleted, 0)=0 AND path = ?",
            (path,),
        ),
    )
    if matching_media:
        log.debug("tube: found local %s", matching_media)
    return matching_media


def _resolve_metadata_match(args, select_sql, paths, matching_media):
    if args.match_column not in ("playlist_path", "path") or args.offline or matching_media:
        return matching_media

    data = tube_backend.get_video_metadata(args, paths[0])
    if not data:
        return matching_media
    if args.match_column not in data:
        log.warning("[%s]: Match column %s not found in tube metadata", paths[0], args.match_column)
        msg = ""
        for key in data:
            preview = str(data[key]).replace("\n", " ")
            if len(preview) > MAX_PREVIEW_LENGTH:
                preview = preview[: MAX_PREVIEW_LENGTH - 3] + "..."
            msg += f"  {key}: {preview}\n"
        log.warning(msg)
        return matching_media

    paths.append(data[args.match_column])
    if paths[1]:
        return list(
            args.db.query(
                f"select {select_sql} from media where coalesce(time_deleted, 0)=0 AND {args.match_column} = ?",
                (paths[1],),
            ),
        )
    return matching_media


def _sort_matching_media(args, matching_media):
    if args.regex_sort:
        from library.text import regex_sort

        return list(reversed(regex_sort.sort_dicts(args, matching_media)))
    if args.cluster_sort:
        from library.text import cluster_sort

        return list(reversed(cluster_sort.sort_dicts(args, matching_media)))
    return matching_media


def _delete_matching_media(args, matching_media):
    web_paths = [row["path"] for row in matching_media if (row["time_deleted"] == 0 or 0) and row["path"].startswith("http")]
    if web_paths:
        post_actions.delete_media(args, web_paths)

    local_paths = [
        row["path"] for row in matching_media if (row["time_deleted"] == 0 or 0) and not row["path"].startswith("http")
    ]
    if local_paths:
        total_size = sum(row["size"] or 0 for row in matching_media if (row["time_deleted"] or 0) == 0)
        print("\n".join(local_paths))
        if devices.confirm(
            f"Would you like to delete these {len(local_paths)} local files ({strings.file_size(total_size)})?",
        ):
            post_actions.delete_media(args, local_paths)


def _block_paths(args, paths, m_columns):
    select_sql = ", ".join(column for column in {"path", "webpath", args.match_column, "size", "playlist_path", "time_deleted"} if column in m_columns)
    unmatched_playlists = []
    for path in paths:
        path_parts = [path]
        if consts.PYTEST_RUNNING or args.force:
            (remove_from_blocklist if args.delete_rows else add_to_blocklist)(args, path_parts)
            continue

        matching_media = _get_matching_media(args, select_sql, path)
        matching_media = _resolve_metadata_match(args, select_sql, path_parts, matching_media)
        if matching_media:
            matching_media = _sort_matching_media(args, matching_media)
            media_printer.media_printer(args, matching_media)
            if args.no_confirm or devices.confirm("Add to blocklist?"):
                add_to_blocklist(args, path_parts)
                _delete_matching_media(args, matching_media)
            continue

        if len(path_parts) < MIN_PLAYLIST_PATH_PARTS:
            unmatched_playlists.append(path_parts)
        else:
            log.info("Blocking URL resolved by tube metadata: %s", path_parts[1])
            add_to_blocklist(args, path_parts)

    if unmatched_playlists:
        log.error("Could not find media matching these URLs/words (rerun with --force to add blocking rules):")
        log.error("  " + " ".join(item[0] for item in unmatched_playlists))


def block(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args()
    m_columns = db_utils.columns(args, "media")
    if args.match_column not in m_columns:
        raise ValueError(
            "Match column does not exist in the media table. You may need to run tubeadd first or check your spelling",
        )

    paths = list(shell_utils.gen_paths(args))
    if not paths:
        _show_block_candidates(args, m_columns)
    elif args.match_column == "playlist_path":
        _block_playlist_paths(args, paths)
    else:
        _block_paths(args, paths, m_columns)
