import argparse

from xklb import dl_extract, tube_backend, usage
from xklb.media import media_printer
from xklb.utils import arg_utils, consts, db_utils, objects, sql_utils
from xklb.utils.log_utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        "library download-status",
        usage=usage.download_status,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--print", "-p", default="p", const="p", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--cols", "-cols", "-col", nargs="*", help="Include a column when printing")
    parser.add_argument("--sort", "-u", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--where", "-w", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--include", "-s", "--search", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--exclude", "-E", "-e", nargs="+", action="extend", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--duration", "-d", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--limit", "-L", "-l", "-queue", "--queue", help=argparse.SUPPRESS)
    parser.add_argument("--safe", "-safe", action="store_true", help="Skip generic URLs")
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
    args.defaults = []

    if args.db:
        args.database = args.db
    args.db = db_utils.connect(args)
    log.info(objects.dict_filter_bool(args.__dict__))

    args.action = consts.SC.download_status
    return args


def download_status() -> None:
    args = parse_args()
    arg_utils.parse_args_sort(args)

    query, bindings = dl_extract.construct_query(args)

    count_paths = ""
    if "time_modified" in query:
        if args.safe:
            args.db.register_function(tube_backend.is_supported, deterministic=True)
            count_paths += f", count(*) FILTER(WHERE cast(STRFTIME('%s', datetime( time_modified, 'unixepoch', '+{args.retry_delay}')) as int) >= STRFTIME('%s', datetime()) and is_supported(path)) failed_recently"
            count_paths += f", count(*) FILTER(WHERE time_modified>0 and cast(STRFTIME('%s', datetime( time_modified, 'unixepoch', '+{args.retry_delay}')) as int) < STRFTIME('%s', datetime()) and is_supported(path)) retry_queued"
            count_paths += (
                ", count(*) FILTER(WHERE COALESCE(time_modified, 0) = 0 and is_supported(path)) never_downloaded"
            )
        else:
            count_paths += f", count(*) FILTER(WHERE cast(STRFTIME('%s', datetime( time_modified, 'unixepoch', '+{args.retry_delay}')) as int) >= STRFTIME('%s', datetime())) failed_recently"
            count_paths += f", count(*) FILTER(WHERE time_modified>0 and cast(STRFTIME('%s', datetime( time_modified, 'unixepoch', '+{args.retry_delay}')) as int) < STRFTIME('%s', datetime())) retry_queued"
            count_paths += ", count(*) FILTER(WHERE COALESCE(time_modified, 0) = 0) never_downloaded"

    query = f"""select
        COALESCE(extractor_key, 'Playlist-less media') extractor_key
        {count_paths}
    from ({query})
    where 1=1
        and COALESCE(time_downloaded, 0) = 0
        and COALESCE(time_deleted, 0) = 0
    group by extractor_key
    order by never_downloaded DESC"""

    media = list(args.db.query(query, bindings))

    if "blocklist" in args.db.table_names():
        blocklist_rules = [{d["key"]: d["value"]} for d in args.db["blocklist"].rows]
        media = sql_utils.block_dicts_like_sql(media, blocklist_rules)

    media_printer.media_printer(args, media, units="extractors")

    if "error" in db_utils.columns(args, "media") and args.verbose >= consts.LOG_INFO:
        query = """
        select error, count(*) count
        from media
        where error is not null
        group by 1
        order by 2 DESC
        """
        errors = list(args.db.query(query))

        common_errors = []
        other_errors = []
        for error in errors:
            if error["count"] < errors[:5][-1]["count"]:
                other_errors.append(error)
            else:
                common_errors.append(error)

        common_errors.append({"error": "Other", "count": len(other_errors)})
        media_printer.media_printer(args, common_errors)
        print(f"Total errors: {sum(d['count'] for d in errors)}")
