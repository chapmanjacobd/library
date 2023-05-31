import argparse, json
from copy import deepcopy
from typing import Tuple

from tabulate import tabulate

from xklb import consts, db, dl_extract, play_actions, tube_backend, usage, utils
from xklb.player import delete_playlists
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        "library download-status",
        usage=usage.download_status,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--aggregate", "-a", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", "-j", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
    parser.add_argument("--errors", "-errors", "--error", action="store_true", help="Show only rows with errors")
    parser.add_argument("--delete", "--remove", "--erase", "--rm", "-rm", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--print", "-p", default=False, const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument(
        "--retry-delay",
        "-r",
        default="14 days",
        help="Must be specified in SQLITE Modifiers format: N hours, days, months, or years",
    )

    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)

    parser.add_argument("database")
    args = parser.parse_args()
    if args.db:
        args.database = args.db
    args.db = db.connect(args)
    log.info(utils.dict_filter_bool(args.__dict__))

    args.action = consts.SC.stats
    return args


def construct_query(args) -> Tuple[str, dict]:
    utils.ensure_playlists_exists(args)
    pl_columns = args.db["playlists"].columns_dict
    args.filter_sql = []
    args.filter_bindings = {}

    args.filter_sql.extend([" and " + w for w in args.where])

    args.table = "playlists"
    if args.db["playlists"].detect_fts():
        if args.include:
            args.table = db.fts_flexible_search(args)
        elif args.exclude:
            db.construct_search_bindings(args, pl_columns)
    else:
        db.construct_search_bindings(args, pl_columns)

    LIMIT = "LIMIT " + str(args.limit) if args.limit else ""
    query = f"""SELECT
        *
    FROM {args.table}
    WHERE 1=1
        and COALESCE(time_deleted,0) = 0
        {" ".join(args.filter_sql)}
        and (category is null or category != '{consts.BLOCK_THE_CHANNEL}')
    ORDER BY 1=1
        {', ' + args.sort if args.sort else ''}
        , path
        , random()
    {LIMIT}
    """

    return query, args.filter_bindings


def printer(args, query, bindings) -> None:
    media = list(args.db.query(query, bindings))
    media = utils.list_dict_filter_bool(media)
    if not media:
        utils.no_media_found()

    tbl = deepcopy(media)
    utils.col_naturaldate(tbl, "avg_time_since_download")
    utils.col_naturalsize(tbl, "size")
    utils.col_duration(tbl, "duration")
    utils.col_duration(tbl, "avg_playlist_duration")

    if args.print and "f" in args.print:
        utils.pipe_print("\n".join([d["path"] for d in media]))
        return
    elif args.json or consts.TERMINAL_SIZE.columns < 80:
        print(json.dumps(tbl, indent=3))
    else:
        tbl = utils.col_resize(tbl, "path", 30)
        tbl = utils.col_resize(tbl, "title", 20)
        tbl = utils.col_resize(tbl, "uploader_url")

        tbl = utils.list_dict_filter_bool(tbl)

        print(tabulate(tbl, tablefmt="fancy_grid", headers="keys", showindex=False))

    print(f"{len(media)} playlists" if len(media) > 1 else "1 playlist")
    duration = sum(m.get("duration") or 0 for m in media)
    if duration > 0:
        duration = utils.human_time(duration)
        if not args.aggregate:
            print("Total duration:", duration)


def download_status() -> None:
    args = parse_args()
    play_actions.parse_args_sort(args)

    if args.delete:
        return delete_playlists(args, args.delete)

    query, bindings = dl_extract.construct_query(args)

    count_paths = ""
    if "time_modified" in query:
        if args.safe:
            args.db.register_function(tube_backend.is_supported, deterministic=True)
            count_paths = (
                ", count(*) FILTER(WHERE COALESCE(time_modified,0) = 0 and is_supported(path)) never_downloaded"
            )
        else:
            count_paths = ", count(*) FILTER(WHERE COALESCE(time_modified,0) = 0) never_downloaded"

    query = f"""select
        coalesce(category, "Playlist-less media") category
        {', ie_key' if 'm.ie_key' in query else ''}
        {', sum(duration) duration' if 'duration' in query else ''}
        {count_paths}
        {', count(*) FILTER(WHERE COALESCE(time_modified,0) > 0 AND error IS NOT NULL) errors' if 'error' in query else ''}
        {', group_concat(distinct error) error_descriptions' if args.errors or 'error' in query and args.verbose >= 1 else ''}
    from ({query}) m
    where 1=1
        and COALESCE(time_downloaded,0) = 0
        and COALESCE(time_deleted,0) = 0
        {'and error is not null' if args.errors else ''}
    group by category{', ie_key' if 'm.ie_key' in query else ''}{', error' if args.errors else ''}
    order by {'errors,' if args.errors else ''} category nulls last"""

    printer(args, query, bindings)
    return None
