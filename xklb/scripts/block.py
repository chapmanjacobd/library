import argparse, sys

import humanize
from tabulate import tabulate

from xklb import consts, db, player, tube_backend, usage, utils
from xklb.consts import SC
from xklb.utils import log


def parse_args():
    parser = argparse.ArgumentParser(
        prog="library block",
        usage=usage.block,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--print", "-p", default="", const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a column when printing")
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--match-column", "-c", default="path", help="Column to block media if text matches")

    parser.add_argument("--force", "-f", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--offline", "--no-tube", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ignore-errors", "--ignoreerrors", "-i", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("database", help=argparse.SUPPRESS)
    parser.add_argument("playlists", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_intermixed_args()

    if args.db:
        args.database = args.db
    args.db = db.connect(args)

    args.playlists = utils.conform(args.playlists)

    args.action = SC.block
    log.info(utils.dict_filter_bool(args.__dict__))

    return args


def add_to_blocklist(args, p):
    p = p.pop()
    args.db["blocklist"].insert({"key": args.match_column, "value": p}, alter=True, replace=True, pk=["key", "value"])


def block(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args()
    m_columns = db.columns(args, "media")
    if args.match_column not in m_columns:
        raise ValueError(
            "Match column does not exist in the media table. You may need to run tubeadd first or check your spelling",
        )

    columns = set(["path", "webpath", args.match_column, "size", "playlist_path", "time_deleted"])
    select_sql = ", ".join(s for s in columns if s in m_columns)

    if not args.playlists:
        if "blocklist" in args.db.table_names():
            media = list(
                args.db.query(
                    """
                    select path
                    from media
                    where coalesce(time_deleted, 0)=0 and path like "http%"
                    """,
                ),
            )
            blocklist = [{d["key"]: d["value"]} for d in args.db["blocklist"].rows]
            player.mark_media_deleted(args, [m["path"] for m in media if utils.is_blocked_dict_like_sql(m, blocklist)])

        args.match_column = "coalesce(webpath, path)"
        candidates = list(
            args.db.query(
                f"""WITH m as (
                    SELECT
                        SUBSTR({args.match_column}
                            , INSTR({args.match_column}, '//') + 2
                            , INSTR( SUBSTR({args.match_column}, INSTR({args.match_column}, '//') + 2), '/') - 1
                        ) AS subdomain
                        , COUNT(*) as count
                        , COUNT(*) filter (where coalesce(time_modified, 0)=0) AS new_links
                        , COUNT(*) filter (where time_modified>0) AS tried
                        , cast(COUNT(*) filter (where time_modified>0) as float) / COUNT(*) AS percent_tried
                        , COUNT(*) filter (where time_downloaded>0) AS succeeded
                        , coalesce(cast(COUNT(*) filter (where time_downloaded > 0) as float) / COUNT(*) filter (where time_modified > 0), 0) AS percent_succeeded
                        , COUNT(*) filter (where coalesce(time_downloaded, 0)=0 AND coalesce(time_modified, 0)>0) AS failed
                        , coalesce(cast(COUNT(*) filter (where coalesce(time_downloaded, 0)=0 AND coalesce(time_modified, 0)>0) as float) / COUNT(*) filter (where time_modified > 0), 0) AS percent_failed
                    FROM media
                    WHERE coalesce(time_deleted, 0)=0
                        AND {args.match_column} LIKE 'http%'
                        AND subdomain != "/"
                    GROUP BY subdomain
                )
                SELECT * from m
                WHERE count != tried
                  AND new_links > 15
                ORDER BY tried > 0 DESC
                    , ntile(3) over (order by new_links) desc
                    , ntile(2) over (order by tried) desc
                    , ntile(3) over (order by percent_failed) desc
                    , ntile(2) over (order by percent_succeeded)
                    , subdomain
                """,
            ),
        )

        player.media_printer(args, candidates, units="subdomains")
        return

    if args.match_column == "playlist_path":
        playlist_paths = list(args.playlists)
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
                AND playlist_id in (
                    SELECT id from playlists
                    WHERE path IN ("""
                + ",".join(["?"] * len(playlist_paths))
                + "))",
                (*playlist_paths,),
            )

        playlist_media = list(
            args.db.query(
                """SELECT path, size FROM media
                WHERE time_deleted = 0
                AND time_downloaded > 0
                AND playlist_id in (
                    SELECT id from playlists
                    WHERE path IN ("""
                + ",".join(["?"] * len(playlist_paths))
                + "))",
                (*playlist_paths,),
            ),
        )
        total_size = sum(d["size"] for d in playlist_media)
        paths_to_delete = [d["path"] for d in playlist_media]
        if paths_to_delete:
            print(paths_to_delete)
            if utils.confirm(
                f"Would you like to delete these {len(paths_to_delete)} local files ({humanize.naturalsize(total_size)})?",
            ):
                player.delete_media(args, paths_to_delete)
        return

    unmatched_playlists = []
    for p in args.playlists:
        p = [p]
        if consts.PYTEST_RUNNING or args.force:
            add_to_blocklist(args, p)
            continue

        matching_media = list(
            args.db.query(f"select {select_sql} from media where {args.match_column} LIKE ?", (p[0],)),
        )

        if not matching_media:
            matching_media = list(args.db.query(f"select {select_sql} from media where path = ?", (p[0],)))
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
                            args.db.query(f"select {select_sql} from media where {args.match_column} = ?", (p[1],)),
                        )

        if not matching_media:
            unmatched_playlists.append(p)
            continue

        try:
            matching_media = list(reversed(utils.cluster_dicts(args, matching_media)))
        except ModuleNotFoundError:
            pass

        tbl = utils.list_dict_filter_bool(matching_media)
        tbl = [
            {
                "title_path": "\n".join(utils.concat(d.get("title"), d.get("webpath"), d["path"])),
                **d,
            }
            for d in tbl
        ]
        tbl = [{k: v for k, v in d.items() if k not in ("title", "path", "webpath")} for d in tbl]
        tbl = utils.col_resize_percent(tbl, "title_path", 40)
        tbl = utils.col_naturalsize(tbl, "size")
        tbl = utils.col_naturaldate(tbl, "time_deleted")
        print(tabulate(tbl, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False))
        if utils.confirm(f"{len(matching_media)} media matching {p}. Add to blocklist?"):
            add_to_blocklist(args, p)
        else:
            continue

        paths_to_delete = [
            d["path"] for d in matching_media if d["time_deleted"] == 0 and not d["path"].startswith("http")
        ]
        if paths_to_delete:
            total_size = sum(d["size"] for d in matching_media if d["time_deleted"] == 0)
            if utils.confirm(
                f"Would you like to delete these {len(paths_to_delete)} local files ({humanize.naturalsize(total_size)})?",
            ):
                player.delete_media(args, paths_to_delete)
        else:
            player.delete_media(
                args,
                [d["path"] for d in matching_media if d["time_deleted"] == 0 and d["path"].startswith("http")],
            )

    if unmatched_playlists:
        log.error("Could not find media matching these URLs/words (rerun with --force to add a blocking rule):")
        log.error("  " + " ".join(t[0] for t in unmatched_playlists))
