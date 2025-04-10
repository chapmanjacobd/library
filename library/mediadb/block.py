import sys

from library import usage
from library.createdb import tube_backend
from library.playback import media_printer, post_actions
from library.utils import arggroups, argparse_utils, consts, db_utils, devices, file_utils, iterables, strings
from library.utils.log_utils import log


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
    args.db["blocklist"].insert({"key": args.match_column, "value": p}, alter=True, replace=True, pk=["key", "value"])


def remove_from_blocklist(args, p):
    p = p.pop()
    with args.db.conn:
        args.db["blocklist"].delete([args.match_column, p])


def block(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args()
    m_columns = db_utils.columns(args, "media")
    if args.match_column not in m_columns:
        raise ValueError(
            "Match column does not exist in the media table. You may need to run tubeadd first or check your spelling",
        )

    columns = {"path", "webpath", args.match_column, "size", "playlist_path", "time_deleted"}

    paths = list(file_utils.gen_paths(args))

    if not paths:
        if "blocklist" in args.db.table_names():
            deleted_count = 0
            blocklist = [(d["key"], d["value"]) for d in args.db["blocklist"].rows if d["key"] in m_columns]
            # TODO: add support for playlists table block rules
            if blocklist:
                # prevent Expression tree is too large (max depth 1000)
                blocklist_chunked = iterables.chunks(blocklist, consts.SQLITE_PARAM_LIMIT // 100)
                for chunk in blocklist_chunked:
                    columns = [t[0] for t in chunk]
                    values = [t[1] for t in chunk]
                    try:
                        with args.db.conn:
                            query = (
                                f"""UPDATE media
                                SET time_deleted = {consts.APPLICATION_START}
                                WHERE COALESCE(time_deleted, 0)=0
                                AND path LIKE "http%"
                                AND ("""
                                + " OR ".join(f"{c} LIKE ?" for c in columns)
                                + ")"
                            )
                            cursor = args.db.conn.execute(query, [*values])
                        deleted_count += cursor.rowcount
                    except Exception:
                        log.exception("Quick cleanup %s", chunk)
                        raise

            if deleted_count > 0:
                log.info(f"Marked {deleted_count} blocked metadata records as deleted")

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
        return

    if args.match_column == "playlist_path":
        playlist_paths = list(paths)
        for p in playlist_paths:
            add_to_blocklist(args, [p])

        with args.db.conn:
            args.db.conn.execute(
                f"""UPDATE playlists
                SET time_deleted={consts.APPLICATION_START}
                WHERE path IN ("""
                + ",".join(["?"] * len(playlist_paths))
                + ")",
                (*playlist_paths,),
            )
        with args.db.conn:
            args.db.conn.execute(
                f"""UPDATE media
                SET time_deleted={consts.APPLICATION_START}
                WHERE path LIKE 'http%'
                AND playlists_id in (
                    SELECT id from playlists
                    WHERE path IN ("""
                + ",".join(["?"] * len(playlist_paths))
                + "))",
                (*playlist_paths,),
            )

        playlist_media = list(
            args.db.query(
                """SELECT path, size FROM media
                WHERE coalesce(time_deleted, 0)=0
                AND time_downloaded > 0
                AND playlists_id in (
                    SELECT id from playlists
                    WHERE path IN ("""
                + ",".join(["?"] * len(playlist_paths))
                + "))",
                (*playlist_paths,),
            ),
        )
        total_size = sum(d["size"] or 0 for d in playlist_media)
        paths_to_delete = [d["path"] for d in playlist_media]
        if paths_to_delete:
            print(paths_to_delete)
            if devices.confirm(
                f"Would you like to delete these {len(paths_to_delete)} local files ({strings.file_size(total_size)})?",
            ):
                post_actions.delete_media(args, paths_to_delete)
        return

    select_sql = ", ".join(s for s in columns if s in m_columns)

    unmatched_playlists = []
    for p in paths:
        p = [p]
        if consts.PYTEST_RUNNING or args.force:
            if args.delete_rows:
                remove_from_blocklist(args, p)
            else:
                add_to_blocklist(args, p)
            continue

        matching_media = list(
            args.db.query(
                f"select {select_sql} from media where coalesce(time_deleted, 0)=0 AND {args.match_column} LIKE ?",
                (p[0],),
            ),
        )

        if not matching_media:
            matching_media = list(
                args.db.query(
                    f"select {select_sql} from media where coalesce(time_deleted, 0)=0 AND path = ?",
                    (p[0],),
                ),
            )
            if matching_media:
                log.debug("tube: found local %s", matching_media)

        if args.match_column in ("playlist_path", "path") and not args.offline and not matching_media:
            data = tube_backend.get_video_metadata(args, p[0])
            if data:
                if args.match_column not in data:
                    log.warning("[%s]: Match column %s not found in tube metadata", p[0], args.match_column)
                    msg = ""
                    for key in data:
                        preview = str(data[key]).replace("\n", " ")
                        if len(preview) > 80:
                            preview = preview[:77] + "..."
                        msg += f"  {key}: {preview}\n"
                    log.warning(msg)
                else:
                    p[1] = data[args.match_column]
                    if p[1]:
                        matching_media = list(
                            args.db.query(
                                f"select {select_sql} from media where coalesce(time_deleted, 0)=0 AND {args.match_column} = ?",
                                (p[1],),
                            ),
                        )

        if not matching_media:
            unmatched_playlists.append(p)
            continue

        if args.regex_sort:
            from library.text import regex_sort

            matching_media = list(reversed(regex_sort.sort_dicts(args, matching_media)))
        elif args.cluster_sort:
            from library.text import cluster_sort

            matching_media = list(reversed(cluster_sort.sort_dicts(args, matching_media)))

        media_printer.media_printer(args, matching_media)
        if args.no_confirm or devices.confirm("Add to blocklist?"):
            add_to_blocklist(args, p)
        else:
            continue

        web_paths_to_delete = [
            d["path"] for d in matching_media if (d["time_deleted"] == 0 or 0) and d["path"].startswith("http")
        ]
        if web_paths_to_delete:
            post_actions.delete_media(args, web_paths_to_delete)

        local_paths_to_delete = [
            d["path"] for d in matching_media if (d["time_deleted"] == 0 or 0) and not d["path"].startswith("http")
        ]
        if local_paths_to_delete:
            total_size = sum(d["size"] or 0 for d in matching_media if (d["time_deleted"] or 0) == 0)
            print("\n".join(local_paths_to_delete))
            if devices.confirm(
                f"Would you like to delete these {len(local_paths_to_delete)} local files ({strings.file_size(total_size)})?",
            ):
                post_actions.delete_media(args, local_paths_to_delete)

    if unmatched_playlists:
        log.error("Could not find media matching these URLs/words (rerun with --force to add blocking rules):")
        log.error("  " + " ".join(t[0] for t in unmatched_playlists))
