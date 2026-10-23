import argparse
from collections import defaultdict

from library import usage
from library.play import media_printer
from library.utils import arggroups, argparse_utils, consts, db_utils, nums, sqlgroups


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=usage.download_status)
    arggroups.sql_fs(parser)
    parser.set_defaults(print="p")

    arggroups.download(parser)

    arggroups.debug(parser)
    arggroups.database(parser)

    parser.set_defaults(fts=False)
    args = parser.parse_args()

    # `arggroups.download()` adds `--safe`/`--media-type` because
    # `construct_download_query` reuses them; validate the combination so `--safe`
    # filters as documented instead of silently no-op'ing with filesystem/text.
    from library.download import download as download_mod

    download_mod.validate_safe(args, parser, extracts_links=False)

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

    for media_row in media:
        _update_extractor_stats(extractor_stats, media_row, retry_delay, args.download_retries)

    media = [{"extractor_key": extractor_key, **d} for extractor_key, d in extractor_stats.items()]
    media = sorted(media, key=lambda x: (-x["never_attempted"], -x["retry_queued"], x["extractor_key"] or ""))

    media_printer.media_printer(args, media, units="extractors")

    _print_errors(args)


def _update_extractor_stats(extractor_stats, media_row, retry_delay, download_retries):
    extractor_key = media_row.get("extractor_key", "Playlist-less media")
    time_downloaded = media_row.get("time_downloaded") or 0
    if "download_attempts" in media_row and (media_row["download_attempts"] or 0) >= download_retries:
        extractor_stats[extractor_key]["retries_exceeded"] += 1
        return
    if time_downloaded > 0 or (
        not media_row["path"].startswith("http") and (media_row.get("webpath") or "").startswith("http")
    ):
        if (time_downloaded + retry_delay) >= consts.APPLICATION_START:
            extractor_stats[extractor_key]["downloaded_recently"] += 1
        return
    if not media_row["path"].startswith("http"):
        return

    modified = media_row.get("time_modified") or 0
    if not modified:
        extractor_stats[extractor_key]["never_attempted"] += 1
    elif modified + retry_delay < consts.APPLICATION_START:
        extractor_stats[extractor_key]["retry_queued"] += 1
    else:
        extractor_stats[extractor_key]["failed_recently"] += 1


def _print_errors(args):
    if "error" not in db_utils.columns(args, "media") or args.verbose < consts.LOG_INFO:
        return
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
        (other_errors if error["count"] < small_group else common_errors).append(error)
    common_errors.append({"error": "Other", "count": len(other_errors)})
    media_printer.media_printer(args, common_errors)
    print(f"Total errors: {sum(d['count'] for d in errors)}")
