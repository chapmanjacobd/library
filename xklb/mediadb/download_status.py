import argparse

from xklb import usage
from xklb.playback import media_printer
from xklb.utils import arggroups, argparse_utils, consts, db_utils, sql_utils, sqlgroups


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.download_status)
    arggroups.sql_fs(parser)
    parser.set_defaults(print="p")

    arggroups.download(parser)

    arggroups.debug(parser)
    arggroups.database(parser)

    parser.set_defaults(fts=False)
    args = parser.parse_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    return args


def download_status() -> None:
    args = parse_args()

    query, bindings = sqlgroups.construct_download_query(args, dl_status=True)

    not_downloaded = 'path like "http%" and COALESCE(time_downloaded, 0) = 0'
    can_download = f"download_attempts <= {args.download_retries}" if "download_attempts" in query else "1=1"
    retry_time = f"cast(STRFTIME('%s', datetime( time_modified, 'unixepoch', '+{args.retry_delay}')) as int)"

    count_paths = ""
    if "time_modified" in query:
        count_paths += f"""
            , count(*) FILTER(WHERE {can_download} and {not_downloaded} and time_modified>0 and {retry_time} < STRFTIME('%s', datetime())) retry_queued
            , count(*) FILTER(WHERE {can_download} and {not_downloaded} and COALESCE(time_modified, 0) = 0) never_attempted
            , count(*) FILTER(WHERE time_downloaded > 0) downloaded
            , count(*) FILTER(WHERE {can_download} and {not_downloaded} and time_modified>0 and {retry_time} >= STRFTIME('%s', datetime())) failed_recently
            """
    if "download_attempts" in query:
        count_paths += f", count(*) FILTER(WHERE {not_downloaded} and download_attempts > {args.download_retries}) retries_exceeded"

    query = f"""select
        COALESCE(extractor_key, 'Playlist-less media') extractor_key
        {count_paths}
    from ({query})
    group by extractor_key
    order by never_attempted DESC, retry_queued DESC, extractor_key"""

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

        small_group = errors[:20][-1]["count"]
        common_errors = []
        other_errors = []
        for error in errors:
            if error["count"] < small_group:
                other_errors.append(error)
            else:
                common_errors.append(error)

        common_errors.append({"error": "Other", "count": len(other_errors)})
        media_printer.media_printer(args, common_errors)
        print(f"Total errors: {sum(d['count'] for d in errors)}")
