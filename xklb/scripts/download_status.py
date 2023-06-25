import argparse, json
from copy import deepcopy

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


def printer(args, query, bindings) -> None:
    media = list(args.db.query(query, bindings))
    media = utils.list_dict_filter_bool(media)
    if not media:
        utils.no_media_found()

    if "blocklist" in args.db.table_names():
        media = utils.block_dicts_like_sql(media, [{d["key"]: d["value"]} for d in args.db["blocklist"].rows])

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

        print(tabulate(tbl, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False))

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
        delete_playlists(args, args.delete)
        return

    query, bindings = dl_extract.construct_query(args)

    count_paths = ""
    if "time_modified" in query:
        if args.safe:
            args.db.register_function(tube_backend.is_supported, deterministic=True)
            count_paths = "count(*) FILTER(WHERE COALESCE(time_modified,0) = 0 and is_supported(path)) never_downloaded"
        else:
            count_paths = "count(*) FILTER(WHERE COALESCE(time_modified,0) = 0) never_downloaded"

    query = f"""select
        {count_paths}
        , extractor_key
        {', sum(duration) duration' if 'duration' in query else ''}
        {', count(*) FILTER(WHERE COALESCE(time_modified,0) > 0 AND error IS NOT NULL) errors' if 'error' in query else ''}
        {', group_concat(distinct error) error_descriptions' if 'error' in query and args.verbose >= 1 else ''}
    from ({query})
    where 1=1
        and COALESCE(time_downloaded,0) = 0
        and COALESCE(time_deleted,0) = 0
    group by extractor_key
    order by never_downloaded"""

    printer(args, query, bindings)

    if "error" in db.columns(args, "media"):
        query = """
        select error, count(*) count
        from media
        where error is not null
        group by 1
        order by 2
        """
        errors = list(args.db.query(query))

        common_errors = []
        other_errors = []
        for error in errors:
            if error["count"] == 1:
                other_errors.append(error)
            else:
                common_errors.append(error)

        common_errors.append({"error": "Other", "count": len(other_errors)})
        common_errors.append({"error": "Total", "count": sum(d["count"] for d in errors)})
        print(tabulate(common_errors, tablefmt=consts.TABULATE_STYLE, headers="keys", showindex=False))
