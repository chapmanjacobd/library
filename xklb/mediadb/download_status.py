import argparse
from collections import defaultdict

from xklb import usage
from xklb.playback import media_printer
from xklb.utils import arggroups, argparse_utils, consts, db_utils, nums, sqlgroups


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
    media = args.db.query(query, bindings)

    extractor_stats = defaultdict(
        lambda: {
            "never_attempted": 0,
            "failed_recently": 0,
            "retry_queued": 0,
            "retries_exceeded": 0,
            "downloaded_recently": 0,
        }
    )

    retry_delay = nums.human_to_seconds(args.retry_delay)

    for m in media:
        extractor_key = m.get("extractor_key", "Playlist-less media")

        if "download_attempts" in m and (m["download_attempts"] or 0) > args.download_retries:
            extractor_stats[extractor_key]["retries_exceeded"] += 1
        elif (m.get("time_downloaded") or 0) > 0 or (
            not m["path"].startswith("http") and (m.get("webpath") or "").startswith("http")
        ):
            if (m["time_downloaded"] + retry_delay) >= consts.APPLICATION_START:
                extractor_stats[extractor_key]["downloaded_recently"] += 1
        elif m["path"].startswith("http"):
            if "time_modified" in m:
                if (m["time_modified"] or 0) > 0 and (m["time_modified"] + retry_delay) < consts.APPLICATION_START:
                    extractor_stats[extractor_key]["retry_queued"] += 1
                elif (m["time_modified"] or 0) > 0 and (m["time_modified"] + retry_delay) >= consts.APPLICATION_START:
                    extractor_stats[extractor_key]["failed_recently"] += 1
                else:  # time_modified == 0
                    extractor_stats[extractor_key]["never_attempted"] += 1
            else:
                extractor_stats[extractor_key]["never_attempted"] += 1

    media = [{"extractor_key": extractor_key, **d} for extractor_key, d in extractor_stats.items()]
    media = sorted(media, key=lambda x: (-x["never_attempted"], -x["retry_queued"], x["extractor_key"] or 0))

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
