import argparse, sys

import requests

from library import usage
from library.createdb import gallery_backend, tube_backend
from library.mediadb import db_media
from library.mediafiles import process_ffmpeg, process_image
from library.playback import media_printer
from library.text import extract_links
from library.utils import (
    arggroups,
    argparse_utils,
    consts,
    db_utils,
    file_utils,
    iterables,
    processes,
    sql_utils,
    strings,
    web,
)
from library.utils.consts import DBType
from library.utils.log_utils import log
from library.utils.sqlgroups import construct_download_query


def parse_args():
    parser = argparse_utils.ArgumentParser(usage=usage.download)
    arggroups.sql_fs(parser)

    parser.add_argument("--clean-path", action=argparse.BooleanOptionalAction, default=True, help="Clean output path")
    arggroups.download(parser)
    arggroups.download_subtitle(parser)
    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.filter_links(parser)

    parser.add_argument("--same-domain", action="store_true", help="Choose a random domain to focus on")

    parser.add_argument("--live", action="store_true", help="Video: Allow live streams to be downloaded")

    parser.add_argument("--small", action="store_true", help="Video: Prefer 480p-like")

    parser.add_argument("--photos", action="store_true", help="Image: Only download JPG and WEBP")
    parser.add_argument("--drawings", action="store_true", help="Image: Only download PNG")
    parser.add_argument("--gifs", action="store_true", help="Image: Only download MP4 and GIFs")

    parser.add_argument("--links", action="store_true", help="Download media linked within pages")

    parser.add_argument("--process", action="store_true", help="Transcode images to AVIF and video/audio to AV1/Opus")
    arggroups.clobber(parser)
    arggroups.process_ffmpeg(parser)
    parser.add_argument("--check-corrupt", "--check-corruption", action="store_true")
    arggroups.media_check(parser)
    parser.set_defaults(same_file_threads=1, full_scan_if_corrupt="7%")
    arggroups.debug(parser)

    arggroups.database(parser)
    arggroups.paths_or_stdin(parser, required=False)

    parser.set_defaults(fts=False)
    args, unk = parser.parse_known_intermixed_args()
    arggroups.args_post(args, parser, create_db=args.database and args.database.endswith((".db", ".sqlite")))

    if unk and not args.profile in (DBType.video, DBType.audio):
        parser.error(f"unrecognized arguments: {' '.join(unk)}")
    args.unk = unk

    if not args.profile and not args.print:
        log.error("Download profile must be specified. Use one of: --video OR --audio OR --image OR --filesystem")
        raise SystemExit(1)

    arggroups.sql_fs_post(args)
    arggroups.filter_links_post(args)
    web.requests_session(args)  # prepare requests session
    arggroups.selenium_post(args)
    arggroups.process_ffmpeg_post(args)
    return args


def download(args=None) -> None:
    if args:
        sys.argv = ["lb", *args]

    args = parse_args()

    m_columns = db_utils.columns(args, "media")

    if "limit" in args.defaults and "media" in args.db.table_names() and "webpath" in m_columns:
        if args.db.pop("SELECT 1 from media WHERE webpath is NULL and path in (SELECT webpath FROM media) LIMIT 1"):
            with args.db.conn:
                args.db.conn.execute(
                    """
                    DELETE from media WHERE path in (
                        SELECT webpath FROM media
                        WHERE error IS NULL OR error NOT LIKE 'Media check failed%'
                    ) AND webpath is NULL
                    """
                )

    args.blocklist_rules = []
    if "blocklist" in args.db.table_names():
        args.blocklist_rules = [{d["key"]: d["value"]} for d in args.db["blocklist"].rows]

    media = list(file_utils.gen_d(args))
    if not media:
        query, bindings = construct_download_query(args)
        media = list(args.db.query(query, bindings))

    if not media:
        processes.no_media_found()

    if args.print:
        media_printer.media_printer(args, media)
        return

    get_inner_urls = iterables.return_unique(extract_links.get_inner_urls, lambda d: d["link"])
    for m in media:
        if args.blocklist_rules and sql_utils.is_blocked_dict_like_sql(m, args.blocklist_rules):
            continue

        if args.safe:
            if (args.profile in (DBType.audio, DBType.video) and not tube_backend.is_supported(m["path"])) or (
                args.profile in (DBType.image,) and not gallery_backend.is_supported(args, m["path"])
            ):
                log.info("[%s]: Skipping unsupported URL (safe_mode)", m["path"])
                continue

        # check if download already attempted recently by another process
        previous_time_attempted = m.get("time_modified") or consts.APPLICATION_START  # 0 is nullified
        if not args.force and "time_modified" in m_columns:
            d = args.db.pop_dict(
                f"""
                SELECT
                    time_modified
                    , time_deleted
                    {", download_attempts" if 'download_attempts' in m_columns else ', 0 as download_attempts'}
                FROM media
                WHERE path=?
                """,
                [m["path"]],
            )
            log.debug(d)
            if d:
                if d["time_deleted"]:
                    log.info(
                        "[%s]: Download was marked as deleted %s ago. Skipping!",
                        m["path"],
                        strings.duration(consts.now() - d["time_deleted"]),
                    )
                    continue
                elif d.get("time_modified") and d["time_modified"] > int(previous_time_attempted):
                    log.info(
                        "[%s]: Download already attempted %s ago. Skipping!",
                        m["path"],
                        strings.duration(consts.now() - d["time_modified"]),
                    )
                    continue
                elif d.get("download_attempts") and d["download_attempts"] > args.download_retries:
                    log.info(
                        "[%s]: Download attempts exceed download retries limit. Skipping!",
                        m["path"],
                    )
                    continue

        try:  # attempt to download
            log.debug(m)

            if args.profile in (DBType.audio, DBType.video):
                tube_backend.download(args, m)
            elif args.profile == DBType.image:
                gallery_backend.download(args, m)
            elif args.profile == DBType.filesystem:
                original_path = m["path"]

                dl_paths = [original_path]
                if args.links:
                    dl_paths = []
                    try:
                        for link_dict in get_inner_urls(args, original_path):
                            dl_paths.append(link_dict["link"])
                    except requests.HTTPError as e:
                        log.warning(
                            "HTTPError %s. Recording download attempt: %s", e.response.status_code, original_path
                        )
                        db_media.download_add(
                            args,
                            webpath=original_path,
                            info=m,
                            error=str(e),
                            mark_deleted=e.response.status_code == 404,
                            delete_webpath_entry=False,
                        )
                        web.post_download(args)
                        continue

                if not dl_paths:
                    log.info("No relevant links in page. Recording download attempt: %s", original_path)
                    db_media.download_add(args, original_path, m, error="No relevant links in page")
                    web.post_download(args)
                    continue

                any_error = False
                for i, dl_path in enumerate(dl_paths):
                    error = None
                    try:
                        local_path = web.download_url(args, dl_path)
                    except RuntimeError as e:
                        local_path = None
                        error = str(e)

                    if local_path and args.process:
                        extension = local_path.rsplit(".", 1)[-1].lower()
                        if extension in consts.AUDIO_ONLY_EXTENSIONS | consts.VIDEO_EXTENSIONS:
                            result = process_ffmpeg.process_path(args, local_path)
                        elif extension in consts.IMAGE_EXTENSIONS:
                            result = process_image.process_path(args, local_path)

                        if result is not None:
                            local_path = str(result)

                    is_not_found = error is not None and "HTTPNotFound" in error
                    if error is not None and "HTTPNotFound" not in error:
                        any_error = True

                    db_media.download_add(
                        args,
                        webpath=original_path,
                        info=m,
                        local_path=local_path,
                        error=error,
                        mark_deleted=is_not_found,
                        delete_webpath_entry=(
                            not any_error if i == len(dl_paths) - 1 else False
                        ),  # only check after last download link was saved
                    )
            else:
                raise NotImplementedError

        except Exception:
            print("db:", args.database)
            raise
